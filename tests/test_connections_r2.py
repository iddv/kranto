"""Connected accounts, round 2 (phases C and D): GitHub (a pasted
fine-grained token, and the device flow behind ``connections.github_client_id``),
Bluesky (loopback OAuth with PAR, PKCE and DPoP; an app password), YouTube (the
owner's own Google client), Product Hunt and Stack Exchange (pasted), each against
a fake provider; YouTube's 30-day cap; and no token anywhere it must not be.

Every token, key, secret and code here is made at runtime (``secrets``); none is a
literal. The fake Bluesky server checks each DPoP proof's signature, method, URL,
nonce and token hash, as a real one does.
"""

import base64
import hashlib
import io
import json
import logging
import secrets
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from kranto import library, source_health
from kranto.config import (
    BudgetConfig,
    Config,
    ConfigError,
    IngestConfig,
    LookConfig,
    MapConfig,
    RetentionConfig,
    _parse_retention,
)
from kranto.connections import Connections, OAuthError, oauth
from kranto.connections import bluesky as bsky_conn
from kranto.connections.vault import Vault
from kranto.retention import retention_days, set_source_retention
from kranto.runtime import open_runtime
from kranto.sources import HTTP, SourceError, build
from kranto.sources import stackexchange as se_source
from kranto.store import Store
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, web_client


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def challenge_of(verifier: str) -> str:
    return b64e(hashlib.sha256(verifier.encode()).digest())


def form_of(request: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def session_jwt(did: str, lifetime: int = 7200, scope: str = "com.atproto.appPass") -> str:
    """A session token shaped like Bluesky's (unsigned: the fake PDS only compares it)."""
    claims = {"scope": scope, "sub": did, "exp": int(time.time()) + lifetime}
    return ".".join([b64e(json.dumps({"alg": "none"}).encode()),
                     b64e(json.dumps(claims).encode()),
                     secrets.token_hex(16)])


# -- fake providers ---------------------------------------------------------------------------


class FakeGitHub:
    def __init__(self):
        self.token = "github_pat_" + secrets.token_hex(30)
        self.classic_scopes = None  # a classic token's X-OAuth-Scopes, if this is one
        self.device_code = secrets.token_hex(20)
        self.user_code = "-".join([secrets.token_hex(2).upper(), secrets.token_hex(2).upper()])
        self.device_replies: list[dict] = []
        self.polls = 0
        self.revoked = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "github.com":
            form = form_of(request)
            if path == "/login/device/code":
                assert form["scope"] == "read:user" and form["client_id"]
                return httpx.Response(200, json={
                    "device_code": self.device_code, "user_code": self.user_code,
                    "verification_uri": "https://github.com/login/device", "expires_in": 900,
                    "interval": 5})
            if path == "/login/oauth/access_token":
                assert form["device_code"] == self.device_code
                self.polls += 1
                return httpx.Response(200, json=self.device_replies.pop(0))
            return httpx.Response(404)
        if request.headers.get("authorization") != f"Bearer {self.token}" or self.revoked:
            return httpx.Response(401, json={"message": "Bad credentials"})
        headers = {"x-oauth-scopes": self.classic_scopes} if self.classic_scopes is not None \
            else {}
        if path == "/user":
            return httpx.Response(200, json={"login": "octo-owner"}, headers=headers)
        if path == "/users/octo-owner/starred":
            assert request.url.params["sort"] == "updated"
            return httpx.Response(200, json=[{"full_name": "automerge/automerge"},
                                             {"full_name": "gone/away"}])
        if path == "/repos/automerge/automerge/releases":
            return httpx.Response(200, json=[
                {"html_url": "https://github.com/automerge/automerge/releases/tag/v3",
                 "name": "v3.0", "body": "Sync is faster", "published_at":
                 "2026-10-01T00:00:00Z", "author": {"login": "someone"}},
                {"html_url": "https://github.com/automerge/automerge/releases/tag/v4",
                 "draft": True, "name": "draft"}])
        return httpx.Response(404)


class FakeBluesky:
    """Bluesky's identity, a PDS, and its authorization server (PAR, PKCE, DPoP)."""

    PDS = "pds.example"
    AS = "auth.example"

    def __init__(self):
        self.did = "did:plc:" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz234567")
                                        for _ in range(24))
        self.handle = "alice.example"
        self.code = secrets.token_hex(12)
        self.access = secrets.token_urlsafe(32)
        self.refresh = secrets.token_urlsafe(32)
        self.scope = " ".join(bsky_conn.SCOPES)
        self.as_nonce = secrets.token_urlsafe(8)
        self.pds_nonce = secrets.token_urlsafe(8)
        self.par: dict = {}
        self.jkt = None
        self.revoked: list[str] = []
        self.password = "-".join(secrets.token_hex(2) for _ in range(4))
        self.sessions: dict[str, str] = {}  # access JWT -> refresh JWT
        self.deleted = False
        # What createSession's access JWT says: a plain app password by default.
        self.session_scope = "com.atproto.appPass"
        self.nonce_refusals = 0

    # A DPoP proof as a real server checks it: signature, method, URL, nonce, key.
    def proof(self, request, *, nonce, token=None):
        proof = request.headers.get("dpop")
        assert proof, "every request carries a DPoP proof"
        head, body, sig = proof.split(".")
        header, payload = json.loads(b64d(head)), json.loads(b64d(body))
        assert header["typ"] == "dpop+jwt" and header["alg"] == "ES256"
        jwk = header["jwk"]
        key = ec.EllipticCurvePublicNumbers(int.from_bytes(b64d(jwk["x"]), "big"),
                                            int.from_bytes(b64d(jwk["y"]), "big"),
                                            ec.SECP256R1()).public_key()
        raw = b64d(sig)
        key.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"),
                                        int.from_bytes(raw[32:], "big")),
                   f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
        url = request.url
        assert payload["htm"] == request.method
        assert payload["htu"] == f"{url.scheme}://{url.host}{url.path}"
        assert "?" not in payload["htu"]
        if token is not None:
            assert payload["ath"] == b64e(hashlib.sha256(token.encode()).digest())
        thumb = jwk["x"] + jwk["y"]
        if self.jkt is None:
            self.jkt = thumb
        assert thumb == self.jkt, "the same key for the whole connection"
        return payload.get("nonce") == nonce

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "public.api.bsky.app" and path.endswith("resolveHandle"):
            assert request.url.params["handle"] == self.handle
            return httpx.Response(200, json={"did": self.did})
        if host == "plc.directory":
            return httpx.Response(200, json={
                "id": self.did, "alsoKnownAs": [f"at://{self.handle}"],
                "service": [{"id": "#atproto_pds", "type": "AtprotoPersonalDataServer",
                             "serviceEndpoint": f"https://{self.PDS}"}]})
        if host == self.PDS and path == "/.well-known/oauth-protected-resource":
            return httpx.Response(200, json={"authorization_servers": [f"https://{self.AS}"]})
        if host == self.AS and path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={
                "issuer": f"https://{self.AS}",
                "pushed_authorization_request_endpoint": f"https://{self.AS}/oauth/par",
                "authorization_endpoint": f"https://{self.AS}/oauth/authorize",
                "token_endpoint": f"https://{self.AS}/oauth/token",  # pragma: allowlist secret
                "revocation_endpoint": f"https://{self.AS}/oauth/revoke",
                "dpop_signing_alg_values_supported": ["ES256"]})
        if host == self.AS:
            return self.auth_server(request, path)
        if host == self.PDS:
            return self.pds(request, path)
        return httpx.Response(404)

    def auth_server(self, request, path):
        form = form_of(request)
        if path == "/oauth/par":
            self.jkt = None  # each sign-in brings its own key; the rest must use it
        if not self.proof(request, nonce=self.as_nonce):
            self.nonce_refusals += 1
            return httpx.Response(400, json={"error": "use_dpop_nonce"},
                                  headers={"dpop-nonce": self.as_nonce})
        if path == "/oauth/par":
            self.par = form
            return httpx.Response(201, json={"request_uri": "urn:ietf:params:oauth:"
                                             "request_uri:" + secrets.token_hex(8),
                                             "expires_in": 60})
        if path == "/oauth/token":
            if form["grant_type"] == "authorization_code":
                if form["code"] != self.code or \
                        challenge_of(form["code_verifier"]) != self.par["code_challenge"] or \
                        form["client_id"] != self.par["client_id"] or \
                        form["redirect_uri"] != self.par["redirect_uri"]:
                    return httpx.Response(400, json={"error": "invalid_grant"})
            elif form.get("refresh_token") != self.refresh:
                return httpx.Response(400, json={"error": "invalid_grant"})
            else:
                self.access, self.refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            return httpx.Response(200, json={
                "access_token": self.access, "token_type": "DPoP", "refresh_token": self.refresh,
                "expires_in": 1800, "scope": self.scope, "sub": self.did})
        if path == "/oauth/revoke":
            self.revoked.append(form["token"])
            return httpx.Response(200)
        return httpx.Response(404)

    def pds(self, request, path):
        if path == "/xrpc/com.atproto.server.createSession":
            body = json.loads(request.content)
            if body != {"identifier": self.did, "password": self.password}:
                return httpx.Response(401, json={"error": "AuthenticationRequired"})
            access = session_jwt(self.did, scope=self.session_scope)
            refresh = session_jwt(self.did, 86400, scope="com.atproto.refresh")
            self.sessions[access] = refresh
            return httpx.Response(200, json={"did": self.did, "handle": self.handle,
                                             "accessJwt": access, "refreshJwt": refresh})
        if path == "/xrpc/com.atproto.server.refreshSession":
            old = request.headers["authorization"].removeprefix("Bearer ")
            if old not in self.sessions.values():
                return httpx.Response(400, json={"error": "ExpiredToken"})
            access, refresh = session_jwt(self.did), session_jwt(self.did, 86400)
            self.sessions = {access: refresh}
            return httpx.Response(200, json={"did": self.did, "accessJwt": access,
                                             "refreshJwt": refresh})
        if path == "/xrpc/com.atproto.server.deleteSession":
            self.deleted = request.headers["authorization"].removeprefix("Bearer ") \
                in self.sessions.values()
            return httpx.Response(200)
        assert request.headers.get("atproto-proxy") == "did:web:api.bsky.app#bsky_appview"
        auth = request.headers.get("authorization", "")
        if auth.startswith("DPoP "):
            token = auth.removeprefix("DPoP ")
            if token != self.access or token in self.revoked:
                return httpx.Response(401, json={"error": "InvalidToken"})
            if not self.proof(request, nonce=self.pds_nonce, token=token):
                self.nonce_refusals += 1
                return httpx.Response(401, json={"error": "use_dpop_nonce"}, headers={
                    "dpop-nonce": self.pds_nonce,
                    "www-authenticate": 'DPoP error="use_dpop_nonce"'})
        elif auth.removeprefix("Bearer ") not in self.sessions:
            return httpx.Response(401, json={"error": "InvalidToken"})
        post = {"uri": f"at://{self.did}/app.bsky.feed.post/3kx", "author": {"handle": "bob"},
                "record": {"text": "Local-first sync engines compared",
                           "createdAt": "2026-10-01T00:00:00Z"}}
        if path == "/xrpc/app.bsky.feed.getTimeline":
            return httpx.Response(200, json={"feed": [{"post": post}]})
        if path == "/xrpc/app.bsky.feed.searchPosts":
            assert request.url.params["q"] == "local first"
            return httpx.Response(200, json={"posts": [post, post]})
        return httpx.Response(404)

    def authorize(self, url: str) -> dict:
        """What the browser does at the authorize page: back with a code."""
        query = parse_qs(urlparse(url).query)
        assert urlparse(url).netloc == self.AS
        assert query["client_id"] == [self.par["client_id"]] and query["request_uri"]
        return {"state": self.par["state"], "code": self.code, "iss": f"https://{self.AS}"}


class FakeGoogle:
    def __init__(self):
        self.client_id = f"{secrets.randbelow(10**12)}-{secrets.token_hex(8)}" \
                         ".apps.googleusercontent.com"
        self.client_secret = secrets.token_urlsafe(24)
        self.code = secrets.token_hex(12)
        self.access = "ya29." + secrets.token_urlsafe(40)
        self.refresh = secrets.token_urlsafe(40)
        self.scope = "https://www.googleapis.com/auth/youtube.readonly"
        self.challenge = None
        self.revoked: list[str] = []
        self.give_refresh = True
        self.units = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "oauth2.googleapis.com" and path == "/token":
            form = form_of(request)
            if form["client_secret"] != self.client_secret or form["client_id"] != self.client_id:
                return httpx.Response(401, json={"error": "invalid_client"})
            if form["grant_type"] == "authorization_code":
                if form["code"] != self.code or challenge_of(form["code_verifier"]) \
                        != self.challenge:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json={
                    "access_token": self.access, "expires_in": 3599, "scope": self.scope,
                    "refresh_token": self.refresh if self.give_refresh else None,
                    "token_type": "Bearer"})
            if form["refresh_token"] != self.refresh or self.refresh in self.revoked:
                return httpx.Response(400, json={"error": "invalid_grant"})
            self.access = "ya29." + secrets.token_urlsafe(40)
            return httpx.Response(200, json={"access_token": self.access, "expires_in": 3599,
                                             "scope": self.scope})
        if host == "oauth2.googleapis.com" and path == "/revoke":
            self.revoked.append(form_of(request)["token"])
            return httpx.Response(200)
        if host != "www.googleapis.com":
            return httpx.Response(404)
        if request.headers.get("authorization") != f"Bearer {self.access}":
            return httpx.Response(401, json={"error": {"code": 401}})
        self.units += 1
        if path == "/youtube/v3/channels":
            return httpx.Response(200, json={"items": [{"snippet": {"title": "Octo"}}]})
        if path == "/youtube/v3/subscriptions":
            if request.url.params.get("pageToken") != "p2":
                return httpx.Response(200, json={"nextPageToken": "p2", "items": [
                    {"snippet": {"resourceId": {"channelId": "UC" + "a" * 22}}}]})
            return httpx.Response(200, json={"items": [
                {"snippet": {"resourceId": {"channelId": "UC" + "b" * 22}}}]})
        if path == "/youtube/v3/playlistItems":
            pid = request.url.params["playlistId"]
            assert pid in ("UU" + "a" * 22, "UU" + "b" * 22)
            vid = (pid[2] * 11)
            return httpx.Response(200, json={"items": [
                {"contentDetails": {"videoId": vid, "videoPublishedAt": "2026-10-02T00:00:00Z"},
                 "snippet": {"title": f"Talk {pid[2]}", "description": "About CRDTs",
                             "channelTitle": "Someone"}},
                {"contentDetails": {"videoId": "x" * 11}, "snippet": {"title": "Private video"}}]})
        return httpx.Response(404)


class FakeProductHunt:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.queries: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": "invalid_oauth_token"})
        body = json.loads(request.content)
        self.queries.append(body)
        if "viewer" in body["query"]:
            viewer = {"user": {"username": "octo-owner"}}
            return httpx.Response(200, json={"data": {"viewer": viewer}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "posts": {
                        "edges": [
                            {
                                "node": {
                                    "id": "1",
                                    "name": "Syncly",
                                    "tagline": "Local-first sync",
                                    "description": "d",
                                    "url": "https://www.producthunt.com/posts/syncly",
                                    "website": "https://syncly.example",
                                    "votesCount": 120,
                                    "createdAt": "2026-10-05T08:00:00Z",
                                }
                            }
                        ]
                    }
                }
            },
        )


class FakeStackExchange:
    def __init__(self):
        self.key = secrets.token_urlsafe(18)
        self.seen: list[httpx.Request] = []
        self.backoff = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        key = request.url.params.get("key")
        if key is not None and key != self.key:
            return httpx.Response(400, json={"error_id": 400, "error_name": "bad_parameter"})
        quota = 10_000 if key else 300
        if request.url.path == "/2.3/info":
            return httpx.Response(200, json={"items": [{}], "quota_max": quota})
        if request.url.path == "/2.3/search/advanced":
            reply = {
                "quota_max": quota,
                "items": [
                    {
                        "link": "https://stackoverflow.com/questions/1/crdt",
                        "title": "CRDT &amp; sync?",
                        "body": "<p>How do I merge?</p>",
                        "creation_date": 1790000000,
                        "tags": ["crdt"],
                        "owner": {"display_name": "asker"},
                    }
                ],
            }
            if self.backoff:
                reply["backoff"] = self.backoff
            return httpx.Response(200, json=reply)
        return httpx.Response(404)


class World:
    """Every fake provider behind one transport, by host."""

    def __init__(self):
        self.github, self.bluesky, self.google = FakeGitHub(), FakeBluesky(), FakeGoogle()
        self.ph, self.se = FakeProductHunt(), FakeStackExchange()
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host in ("api.github.com", "github.com"):
            return self.github(request)
        if host.endswith("googleapis.com"):
            return self.google(request)
        if host == "api.producthunt.com":
            return self.ph(request)
        if host == "api.stackexchange.com":
            return self.se(request)
        if host == "hn.algolia.com":
            return httpx.Response(200, json={"hits": []})
        return self.bluesky(request)


@pytest.fixture
def machine_id(tmp_path):
    path = tmp_path / "machine-id"
    path.write_text(secrets.token_hex(16) + "\n")
    return path


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(se_source, "_backoff_until", 0.0)


class Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


@pytest.fixture
def world():
    return World()


def make_conns(store, tmp_path, world, machine_id, **kw):
    http = HTTP(transport=httpx.MockTransport(world), resolver=lambda h: ["93.184.216.34"])
    return Connections(store, tmp_path / "data", http, machine_id=machine_id, **kw)


# -- GitHub ---------------------------------------------------------------------------------


def test_github_fine_grained_token_is_tested_kept_and_reads_starred_releases(
    store, tmp_path, world, machine_id
):
    conns = make_conns(store, tmp_path, world, machine_id)
    conn = conns.paste("github", {"token": world.github.token})
    assert conn["account"] == "@octo-owner" and conn["instance"] == "github.com"
    assert json.loads(conn["scopes"]) == ["public repositories, read-only"]
    src = build("github", {"what": "starred_releases"}, conns.http, connections=conns)
    [item] = src.fetch()
    assert item.title == "automerge/automerge v3.0" and item.url.endswith("/tag/v3")
    assert "someone" not in json.dumps([item.title, item.body])
    gh = [r for r in world.requests if r.url.host == "api.github.com"]
    assert all(r.headers["authorization"] == f"Bearer {world.github.token}" for r in gh)
    assert all(world.github.token not in str(r.url) for r in world.requests)
    assert conns.test(conn["id"])["ok"]
    note = conns.disconnect(conn["id"])
    assert "deleted here" in note and "Personal access tokens" in note
    assert conns.vault.get(f"conn:{conn['id']}") is None


def test_github_classic_token_that_can_write_is_refused_and_not_kept(
    store, tmp_path, world, machine_id
):
    conns = make_conns(store, tmp_path, world, machine_id)
    world.github.classic_scopes = "repo, read:user"
    with pytest.raises(OAuthError, match="more than read") as info:
        conns.paste("github", {"token": world.github.token})
    assert world.github.token not in str(info.value)
    assert conns.accounts() == [] and conns.vault.keys() == []
    world.github.classic_scopes = ""
    assert conns.paste("github", {"token": world.github.token})["account"] == "@octo-owner"
    with pytest.raises(OAuthError, match="refused this token"):
        conns.paste("github", {"token": secrets.token_hex(20)})
    with pytest.raises(OAuthError, match="required"):
        conns.paste("github", {"token": "  "})


def test_github_device_flow_is_off_without_a_client_id(store, tmp_path, world, machine_id):
    conns = make_conns(store, tmp_path, world, machine_id)
    with pytest.raises(OAuthError, match="github_client_id"):
        conns.device_start("github")
    github = next(p for p in conns.provider_info() if p["key"] == "github")
    assert github["device"] is False and github["device_steps"]
    assert any("Enable Device Flow" in s for s in github["device_steps"])


def test_github_device_flow_honours_interval_and_slow_down(store, tmp_path, world, machine_id):
    clock = Clock()
    conns = make_conns(
        store,
        tmp_path,
        world,
        machine_id,
        github_client_id="Iv1." + secrets.token_hex(8),
        clock=clock,
    )
    cookie, shown = conns.device_start("github")
    assert shown["user_code"] == world.github.user_code and shown["interval"] == 5
    assert world.github.device_code not in json.dumps(shown) + cookie
    row = store.query_one("SELECT * FROM oauth_states")
    assert world.github.device_code not in json.dumps(dict(row))
    # Polled too early: GitHub is not asked.
    assert conns.device_poll("github", cookie) == {"state": "pending", "interval": 5}
    assert world.github.polls == 0
    world.github.device_replies = [
        {"error": "authorization_pending"},
        {"error": "slow_down", "interval": 10},
        {
            "access_token": "gho_" + secrets.token_hex(18),
            "scope": "read:user",
            "token_type": "bearer",
        },
    ]
    clock.now += 5
    assert conns.device_poll("github", cookie)["state"] == "pending"
    clock.now += 5
    assert conns.device_poll("github", cookie) == {"state": "pending", "interval": 10}
    clock.now += 9
    conns.device_poll("github", cookie)
    assert world.github.polls == 2, "slow_down's new interval is honoured"
    world.github.token = world.github.device_replies[0]["access_token"]
    clock.now += 1
    done = conns.device_poll("github", cookie)
    assert done["state"] == "connected" and done["account"] == "@octo-owner"
    with pytest.raises(OAuthError, match="already used"):
        conns.device_poll("github", cookie)
    with pytest.raises(OAuthError, match="does not match"):
        cookie2, _ = conns.device_start("github")
        conns.device_poll("github", cookie2.split(".")[0] + ".x" + secrets.token_hex(8))


def test_github_device_flow_refuses_a_wider_grant(store, tmp_path, world, machine_id):
    clock = Clock()
    conns = make_conns(
        store,
        tmp_path,
        world,
        machine_id,
        github_client_id="Iv1." + secrets.token_hex(8),
        clock=clock,
    )
    cookie, _ = conns.device_start("github")
    world.github.device_replies = [
        {"access_token": "gho_" + secrets.token_hex(18), "scope": "repo,read:user"}
    ]
    clock.now += 6
    with pytest.raises(OAuthError, match="more than read:user"):
        conns.device_poll("github", cookie)
    assert conns.accounts() == []


# -- Bluesky ----------------------------------------------------------------------------------


def bluesky_connect(conns, world, redirect="http://127.0.0.1:8765/connections/bluesky/callback"):
    url, state_id = conns.start("bluesky", "@Alice.Example", redirect)
    return conns.finish("bluesky", str(state_id), world.bluesky.authorize(url))


def test_bluesky_oauth_is_a_loopback_client_with_par_pkce_and_dpop(
    store, tmp_path, world, machine_id
):
    fake = world.bluesky
    conns = make_conns(store, tmp_path, world, machine_id)
    redirect = "http://127.0.0.1:8765/connections/bluesky/callback"
    url, state_id = conns.start("bluesky", "alice.example", redirect)
    par = fake.par
    client = urlparse(par["client_id"])
    assert (client.scheme, client.netloc, client.path) == ("http", "localhost", "")
    assert parse_qs(client.query)["redirect_uri"] == [redirect]
    assert par["redirect_uri"] == redirect and par["code_challenge_method"] == "S256"
    assert par["login_hint"] == "alice.example"
    # Only read calls: no transition:generic, no repo: or blob:, no write.
    scopes = par["scope"].split()
    assert scopes[0] == "atproto" and all(
        s.startswith("rpc:app.bsky.feed.get") or s.startswith("rpc:app.bsky.feed.search")
        for s in scopes[1:]
    )
    assert not any(s.startswith(("transition:", "repo:", "blob:")) for s in scopes)
    assert all("aud=did:web:api.bsky.app%23bsky_appview" in s for s in scopes[1:])
    assert fake.nonce_refusals == 1, "PAR is retried once with the server's DPoP nonce"
    # The verifier, the DPoP key and the state are not in the library.
    row = json.dumps(dict(store.query_one("SELECT * FROM oauth_states")))
    assert par["state"] not in row and "PRIVATE KEY" not in row
    conn = conns.finish("bluesky", str(state_id), fake.authorize(url))
    assert conn["account"] == "@alice.example" and conn["instance"] == "bsky.app"
    assert json.loads(conn["scopes"]) == list(bsky_conn.SCOPES)

    home = build("bluesky", {"what": "home"}, conns.http, connections=conns)
    [item] = home.fetch()
    assert item.title.startswith("Local-first") and "bob" not in item.body
    assert fake.nonce_refusals == 2, "the PDS's nonce is learned once, then reused"
    search = build(
        "bluesky", {"what": "search", "query": "local first"}, conns.http, connections=conns
    )
    assert len(search.fetch()) == 2 and fake.nonce_refusals == 2
    assert conns.test(conn["id"])["ok"]

    # Refresh with DPoP when the token is about to expire.
    old = fake.access
    conns.vault.update(f"conn:{conn['id']}", expires_at=time.time() + 10)
    home.fetch()
    assert fake.access != old
    # Disconnect revokes at the authorization server.
    assert "revoked" in conns.disconnect(conn["id"])
    assert fake.refresh in fake.revoked and fake.access in fake.revoked


def test_bluesky_refuses_a_wider_grant_another_issuer_or_another_account(
    store, tmp_path, world, machine_id
):
    fake = world.bluesky
    conns = make_conns(store, tmp_path, world, machine_id)
    fake.scope = " ".join(bsky_conn.SCOPES) + " transition:generic"
    with pytest.raises(OAuthError, match="read calls asked for"):
        bluesky_connect(conns, world)
    assert fake.access in fake.revoked and conns.accounts() == []
    fake.scope = " ".join(bsky_conn.SCOPES)
    url, state_id = conns.start("bluesky", "alice.example", "http://127.0.0.1:1/cb")
    query = {**fake.authorize(url), "iss": "https://evil.example"}
    with pytest.raises(OAuthError, match="another sign-in server"):
        conns.finish("bluesky", str(state_id), query)
    url, state_id = conns.start("bluesky", "alice.example", "http://127.0.0.1:1/cb")
    query = {k: v for k, v in fake.authorize(url).items() if k != "iss"}
    with pytest.raises(OAuthError, match="another sign-in server"):
        conns.finish("bluesky", str(state_id), query)
    real = fake.did
    url, state_id = conns.start("bluesky", "alice.example", "http://127.0.0.1:1/cb")
    fake.did = "did:plc:" + "b" * 24
    fake.revoked.clear()
    with pytest.raises(OAuthError, match="another account"):
        conns.finish("bluesky", str(state_id), fake.authorize(url))
    assert fake.access in fake.revoked, "a token for another account is not left live"
    fake.did = real
    assert conns.accounts() == []


def test_oauth_state_is_claimed_once(store, tmp_path, machine_id):
    vault = Vault(tmp_path / "secrets", machine_id=machine_id)
    started = oauth.start(store, vault, "mastodon", "m.example", "http://127.0.0.1:1/cb")
    oauth.consume(store, vault, "mastodon", str(started.state_id), started.state)
    with pytest.raises(OAuthError, match="already used"):
        oauth.consume(store, vault, "mastodon", str(started.state_id), started.state)


def test_bluesky_app_password_keeps_the_session_never_the_password(
    store, tmp_path, world, machine_id
):
    fake = world.bluesky
    conns = make_conns(store, tmp_path, world, machine_id)
    with pytest.raises(OAuthError, match="refused"):
        conns.paste("bluesky", {"handle": fake.handle, "app_password": "a" * 19})
    with pytest.raises(OAuthError) as wrong_box:
        conns.paste("bluesky", {"handle": fake.password, "app_password": fake.password})
    assert fake.password not in str(wrong_box.value), "a misplaced password is not echoed"
    for scope in ("com.atproto.access", "com.atproto.appPassPrivileged"):
        fake.session_scope = scope
        with pytest.raises(OAuthError, match="not an app password without DM access"):
            conns.paste("bluesky", {"handle": fake.handle, "app_password": fake.password})
        assert fake.deleted and conns.accounts() == []
        fake.deleted = False
    fake.session_scope = "com.atproto.appPass"
    conn = conns.paste("bluesky", {"handle": fake.handle, "app_password": fake.password})
    assert conn["account"] == "@alice.example"
    assert json.loads(conn["scopes"]) == ["app password"]
    vault = Vault(tmp_path / "data" / "secrets", machine_id=machine_id)
    stored = vault.keys()
    assert fake.password not in json.dumps([vault.get(k) for k in stored])
    src = build("bluesky", {"what": "home"}, conns.http, connections=conns)
    assert len(src.fetch()) == 1
    conns.vault.update(f"conn:{conn['id']}", expires_at=time.time())
    assert len(src.fetch()) == 1, "refreshed with refreshSession"
    assert "revoked" in conns.disconnect(conn["id"]) and fake.deleted


def test_bluesky_sign_in_must_start_on_127_0_0_1(rig):
    rt, _ = rig
    with web_client(create_app(rt), "http://localhost:8765") as web:
        r = web.post("/connections/bluesky/start", json={"handle": "alice.example"})
    assert r.status_code == 400 and "127.0.0.1" in r.json()["error"]


# -- YouTube --------------------------------------------------------------------------------


def youtube_connect(conns, world, redirect="http://127.0.0.1:8765/connections/youtube/callback"):
    url, state_id = conns.start("youtube", "", redirect)
    query = parse_qs(urlparse(url).query)
    world.google.challenge = query["code_challenge"][0]
    return conns.finish(
        "youtube", str(state_id), {"state": query["state"][0], "code": world.google.code}
    )


def test_youtube_needs_the_owners_client_then_signs_in_read_only(
    store, tmp_path, world, machine_id
):
    g = world.google
    conns = make_conns(store, tmp_path, world, machine_id)
    with pytest.raises(OAuthError, match="client id and secret first"):
        conns.start("youtube", "", "http://127.0.0.1:1/cb")
    with pytest.raises(OAuthError, match="googleusercontent"):
        conns.set_client("youtube", {"client_id": "nope", "client_secret": g.client_secret})
    conns.set_client("youtube", {"client_id": g.client_id, "client_secret": g.client_secret})
    info = next(p for p in conns.provider_info() if p["key"] == "youtube")
    assert info["client_set"] is True and len(info["steps"]) >= 8
    assert g.client_secret not in json.dumps(conns.provider_info())

    url, _ = conns.start("youtube", "", "http://127.0.0.1:8765/connections/youtube/callback")
    query = parse_qs(urlparse(url).query)
    assert urlparse(url).netloc == "accounts.google.com"
    assert query["scope"] == ["https://www.googleapis.com/auth/youtube.readonly"]
    assert query["access_type"] == ["offline"] and query["code_challenge_method"] == ["S256"]
    assert "client_secret" not in query
    conn = youtube_connect(conns, world)
    assert conn["account"] == "Octo"

    src = build("youtube", {"what": "subscriptions"}, conns.http, connections=conns)
    items = src.fetch()
    assert [i.title for i in items] == ["Talk a", "Talk b"], "private videos are skipped"
    assert items[0].url == "https://www.youtube.com/watch?v=" + "a" * 11
    assert "Someone" not in json.dumps([i.body for i in items])
    # Refresh before expiry; a refresh Google refuses marks it Needs login.
    old = g.access
    conns.vault.update(f"conn:{conn['id']}", expires_at=time.time() + 5)
    src.fetch()
    assert g.access != old
    g.revoked.append(g.refresh)
    conns.vault.update(f"conn:{conn['id']}", expires_at=time.time() + 5)
    with pytest.raises(SourceError) as info:
        src.fetch()
    assert info.value.needs_login
    assert conns.current("youtube", None)["state"] == "needs_login"
    g.revoked.clear()
    assert "revoked" in conns.disconnect(conn["id"]) and g.revoked == [g.refresh]
    conns.clear_client("youtube")
    assert conns.providers["youtube"].client() is None


def test_youtube_wider_grant_is_revoked_and_refused(store, tmp_path, world, machine_id):
    g = world.google
    conns = make_conns(store, tmp_path, world, machine_id)
    conns.set_client("youtube", {"client_id": g.client_id, "client_secret": g.client_secret})
    g.scope += " https://www.googleapis.com/auth/youtube"
    with pytest.raises(OAuthError, match="more than read-only"):
        youtube_connect(conns, world)
    assert g.revoked and conns.accounts() == []
    g.scope, g.give_refresh = "https://www.googleapis.com/auth/youtube.readonly", False
    g.revoked.clear()
    with pytest.raises(OAuthError, match="no refresh token"):
        youtube_connect(conns, world)
    assert g.revoked == [g.access] and conns.accounts() == [], "not kept, not left live"


def test_youtube_is_kept_at_most_30_days(store):
    with pytest.raises(ConfigError, match="youtube must be between 1 and 30"):
        _parse_retention({"by_kind": {"youtube": 90}})
    with pytest.raises(ConfigError, match="youtube"):
        _parse_retention({"by_kind": {"youtube": 0}})
    assert _parse_retention({"by_kind": {"youtube": 14}}).days_for_kind("youtube") == 14
    assert RetentionConfig(default_days=90).days_for_kind("youtube") == 30
    assert RetentionConfig(default_days=0).days_for_kind("youtube") == 30
    assert RetentionConfig(default_days=0).days_for_kind("rss") == 0
    sid = library.add_source(store, "youtube", {"what": "subscriptions"}, label="subs")
    with pytest.raises(ValueError, match="at most 30 days"):
        set_source_retention(store, sid, 90)
    with pytest.raises(ValueError, match="at most 30 days"):
        set_source_retention(store, sid, 0)
    set_source_retention(store, sid, 7)
    assert retention_days(store, RetentionConfig())[sid] == 7


# -- Product Hunt and Stack Exchange ----------------------------------------------------------


def test_product_hunt_developer_token(store, tmp_path, world, machine_id):
    conns = make_conns(store, tmp_path, world, machine_id)
    with pytest.raises(OAuthError, match="refused this token"):
        conns.paste("producthunt", {"token": secrets.token_urlsafe(20)})
    conn = conns.paste("producthunt", {"token": world.ph.token})
    assert conn["account"] == "@octo-owner" and json.loads(conn["scopes"]) == ["public"]
    src = build(
        "producthunt",
        {"what": "launches", "topic": "developer-tools"},
        conns.http,
        connections=conns,
    )
    [item] = src.fetch()
    assert item.title == "Syncly: Local-first sync" and item.link == "https://syncly.example"
    assert item.meta["producthunt"]["votes"] == 120
    assert world.ph.queries[-1]["variables"]["topic"] == "developer-tools"
    with pytest.raises(SourceError) as info:
        build("producthunt", {"what": "launches"}, conns.http, connections=None)
    assert info.value.needs_login


def test_stack_exchange_key_is_optional_and_never_in_an_error(store, tmp_path, world, machine_id):
    conns = make_conns(store, tmp_path, world, machine_id)
    params = {"site": "stackoverflow.com", "query": "crdt"}
    # Without a key it reads at the smaller allowance.
    [item] = build("stackexchange", params, conns.http, connections=conns).fetch()
    assert item.title == "CRDT & sync?" and "asker" not in item.body
    assert "key" not in world.se.seen[-1].url.params
    with pytest.raises(OAuthError, match="did not accept the key") as info:
        conns.paste("stackexchange", {"key": secrets.token_urlsafe(18)})
    conn = conns.paste("stackexchange", {"key": world.se.key})
    assert conn["account"] == "app key, 10,000 requests a day"
    build("stackexchange", params, conns.http, connections=conns).fetch()
    assert world.se.seen[-1].url.params["key"] == world.se.key
    assert world.se.key not in str(info.value)
    # An error names the URL, never the key in its query string.
    failing = make_conns(store, tmp_path, lambda r: httpx.Response(503), machine_id)
    with pytest.raises(SourceError) as err:
        build("stackexchange", params, failing.http, connections=conns).fetch()
    assert world.se.key not in str(err.value)
    # The API's backoff is honoured.
    world.se.backoff = 30
    build("stackexchange", params, conns.http, connections=conns).fetch()
    asked = len(world.se.seen)
    with pytest.raises(SourceError, match="pause"):
        build("stackexchange", params, conns.http, connections=conns).fetch()
    assert len(world.se.seen) == asked


# -- the web routes, end to end, and where a token must never be -----------------------------


def judge_reply(body):
    if "first, quick look" in body["messages"][0]["content"]:
        return chat_response(json.dumps({"pass": True, "reason": "ok"}))
    return chat_response(
        json.dumps(
            {
                "kind": "beat",
                "summary": "s",
                "why_it_matters": "w",
                "content_quality": 0.9,
                "durability": 0.9,
                "opportunity": 0.9,
                "override": False,
                "tags": ["t"],
            }
        )
    )


@pytest.fixture
def rig(tmp_path, embedder, machine_id):
    world = World()
    store = Store.open(tmp_path / "data" / "kranto.db")
    cfg = Config(
        root=tmp_path,
        llm=llm_config(),
        budget=BudgetConfig(monthly_usd=10),
        ingest=IngestConfig(fetch_full_text=False),
        map=MapConfig(),
        look=LookConfig(enabled=False),
    )
    http = HTTP(transport=httpx.MockTransport(world), resolver=lambda h: ["93.184.216.34"])
    conns = Connections(
        store,
        cfg.data_dir,
        http,
        machine_id=machine_id,
        github_client_id="Iv1." + secrets.token_hex(8),
    )
    from kranto.llm import LLMClient

    client = LLMClient(
        store,
        cfg.llm,
        cfg.budget,
        api_key="k",
        transport=httpx.MockTransport(lambda r: judge_reply(json.loads(r.content))),
    )
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=client, http=http, connections=conns)
    yield rt, world
    rt.close()


def test_every_provider_through_the_web_and_no_secret_anywhere(rig, caplog):
    rt, world = rig
    caplog.set_level(logging.DEBUG)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        listing = web.get("/api/connections").json()
        keys = [p["key"] for p in listing["providers"] if p["state"] == "available"]
        assert keys == [
            "mastodon",
            "bluesky",
            "github",
            "youtube",
            "producthunt",
            "stackexchange",
            "reddit",
            "x",
            "mastodon_post",
            "bluesky_post",
            "sanity",
            "resend",
            "buttondown",
        ]
        assert set(listing["callback"]) == {"mastodon", "bluesky", "youtube", "x", "mastodon_post"}
        github = next(p for p in listing["providers"] if p["key"] == "github")
        assert github["device"] is True

        # Pasted credentials.
        r = web.post("/api/connections/github/credentials", json={"token": world.github.token})
        assert r.json()["ok"] and r.json()["account"] == "@octo-owner"
        assert web.post(
            "/api/connections/producthunt/credentials", json={"token": world.ph.token}
        ).json()["ok"]
        assert web.post(
            "/api/connections/stackexchange/credentials", json={"key": world.se.key}
        ).json()["ok"]
        bad = web.post("/api/connections/github/credentials", json={"token": secrets.token_hex(20)})
        assert bad.status_code == 400 and "refused" in bad.json()["error"]

        # YouTube: the owner's client, then the browser sign-in.
        g = world.google
        assert web.post(
            "/api/connections/youtube/credentials",
            json={"client_id": g.client_id, "client_secret": g.client_secret},
        ).json()["ok"]
        start = web.post("/connections/youtube/start", json={})
        query = parse_qs(urlparse(start.json()["authorize_url"]).query)
        assert query["redirect_uri"] == ["http://127.0.0.1:8765/connections/youtube/callback"]
        g.challenge = query["code_challenge"][0]
        done = web.get(
            "/connections/youtube/callback",
            params={"state": query["state"][0], "code": g.code},
            follow_redirects=False,
        )
        assert "Connected" in done.headers["location"] or "connected" in done.headers["location"]

        # Bluesky: OAuth with DPoP, through the callback.
        start = web.post("/connections/bluesky/start", json={"handle": "alice.example"})
        assert start.status_code == 200, start.text
        back = world.bluesky.authorize(start.json()["authorize_url"])
        done = web.get("/connections/bluesky/callback", params=back, follow_redirects=False)
        assert "error" not in done.headers["location"], done.headers["location"]

        # GitHub's device flow, as the page drives it.
        dev = web.post("/connections/github/device")
        assert dev.status_code == 200 and dev.json()["user_code"] == world.github.user_code
        assert "afk_device" in dev.headers["set-cookie"]
        assert "httponly" in dev.headers["set-cookie"].lower()
        assert web.post("/connections/github/device/poll").json()["state"] == "pending"

        accounts = web.get("/api/connections").json()["accounts"]
        assert {a["provider"] for a in accounts} == {
            "github",
            "producthunt",
            "stackexchange",
            "youtube",
            "bluesky",
        }

        # Sources from the login presets: previewed, added, then fetched by a run.
        added = []
        for preset, fields in [
            ("github.starred", {}),
            ("youtube.subscriptions", {}),
            ("bluesky.home", {}),
            ("bluesky.search", {"query": "local first"}),
            ("producthunt.launches", {"topic": "developer-tools"}),
            ("stackexchange.search", {"site": "stackoverflow.com", "query": "crdt"}),
        ]:
            preview = web.post("/api/sources/preview", json={"preset": preset, "fields": fields})
            assert preview.status_code == 200, (preset, preview.text)
            assert preview.json()["items"] >= 1, preset
            r = web.post("/api/sources", json={"preset": preset, "fields": fields})
            assert r.status_code == 200, (preset, r.text)
            added.append(r.json()["id"])
        rows = {s["id"]: s for s in web.get("/api/sources").json()["sources"]}
        youtube_id = added[1]
        assert rows[youtube_id]["retention_days"] == 30
        assert rows[added[5]]["connection"] == "stackexchange"
        detail = web.get(f"/api/sources/{youtube_id}").json()
        assert "30 days" in detail["how"]["terms"]
        # Each account lists the sources that use it.
        using = {
            a["provider"]: len(a["sources"]) for a in web.get("/api/connections").json()["accounts"]
        }
        assert using == {
            "github": 1,
            "youtube": 1,
            "bluesky": 2,
            "producthunt": 1,
            "stackexchange": 1,
        }

        from kranto.tick import run_ingest

        report = run_ingest(
            rt.cfg,
            rt.store,
            rt.llm,
            rt.embedder,
            rt.http,
            connections=rt.connections,
            lock_path=rt.cfg.data_dir / "l.lock",
        )
        states = {s.source_id: s.fetch_state for s in report.sources}
        assert all(states[i] == "ok" for i in added), states

        # A revoked GitHub token: the next fetch is Needs login, and the menu says so.
        world.github.revoked = True
        assert web.post(f"/api/sources/{added[0]}/fetch").json()["state"] == "needs_login"
        assert web.get("/api/sources").json()["connections_need_you"] == 1

        pages = [
            web.get(p).text
            for p in (
                "/api/connections",
                "/api/sources",
                "/api/catalog",
                f"/api/sources/{added[0]}",
                "/connections",
                "/topics",
            )
        ]
        for a in web.get("/api/connections").json()["accounts"]:
            web.post(f"/api/connections/{a['id']}/disconnect")

    secret_values = [
        world.github.token,
        world.ph.token,
        world.se.key,
        g.client_secret,
        g.access,
        g.refresh,
        g.code,
        world.bluesky.access,
        world.bluesky.refresh,
        world.bluesky.code,
        world.github.device_code,
    ]
    for text in pages:
        for s in secret_values:
            assert s not in text
        assert "PRIVATE KEY" not in text
    server_log = "\n".join(
        r.getMessage() for r in caplog.records if "127.0.0.1:8765" not in r.getMessage()
    )
    for s in secret_values:
        assert s not in server_log
    rt.store.query("PRAGMA wal_checkpoint(FULL)")
    db_bytes = b"".join(p.read_bytes() for p in rt.cfg.data_dir.glob("kranto.db*"))
    out = io.StringIO()
    for table in rt.store.append_only_tables() + ["settings"]:
        rt.store.export_jsonl(table, out)
    events = json.dumps([dict(r) for r in rt.store.query("SELECT * FROM connection_events")])
    fetches = json.dumps([dict(r) for r in rt.store.query("SELECT * FROM source_fetches")])
    raw = (rt.cfg.data_dir / "secrets" / "connections.json").read_bytes()
    for s in secret_values:
        assert s.encode() not in db_bytes and s.encode() not in raw
        assert s not in out.getvalue() and s not in events and s not in fetches
    assert b"PRIVATE KEY" not in db_bytes and b"PRIVATE KEY" not in raw


def test_plain_connections_page_offers_every_provider_without_javascript(rig):
    rt, world = rig
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        page = web.get("/connections").text
        for action in (
            "/connections/mastodon/start",
            "/connections/bluesky/start",
            "/connections/github/credentials",
            "/connections/youtube/credentials",
            "/connections/producthunt/credentials",
            "/connections/stackexchange/credentials",
        ):
            assert f'action="{action}"' in page
        assert 'type="password"' in page and "Fine-grained" in page
        r = web.post(
            "/connections/github/credentials",
            data={"token": world.github.token},
            follow_redirects=False,
        )
        assert r.status_code == 303 and "Connected+GitHub" in r.headers["location"]
        assert world.github.token not in r.headers["location"]


def test_preview_of_a_login_preset_without_an_account_says_needs_login(rig):
    rt, _ = rig
    with pytest.raises(SourceError) as info:
        source_health.preview(rt, "github.starred", {}, None)
    assert info.value.needs_login and "GitHub" in str(info.value)
