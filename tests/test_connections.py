"""Connected accounts (section 3): the vault, state and PKCE, Mastodon
against a fake instance, needs-login, and no token anywhere it must not be.

Every token, secret and code here is made at runtime (``secrets``); none is a literal.
"""

import base64
import hashlib
import io
import json
import logging
import os
import secrets
import stat
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from kranto import library, scrub
from kranto.config import BudgetConfig, Config, IngestConfig, LookConfig, MapConfig
from kranto.connections import Connections, OAuthError, Secret, oauth
from kranto.connections.vault import Vault, VaultError
from kranto.runtime import open_runtime
from kranto.sources import HTTP, SourceError
from kranto.store import Store, iso, utcnow
from kranto.tick import run_ingest
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, web_client

INSTANCE = "masto.example"
SCOPES = "read:accounts read:statuses read:lists"


@pytest.fixture
def machine_id(tmp_path):
    path = tmp_path / "machine-id"
    path.write_text(secrets.token_hex(16) + "\n")
    return path


class FakeMastodon:
    """A Mastodon instance as an httpx transport: apps, OAuth with PKCE, timelines."""

    def __init__(self):
        self.client_id = "cid-" + secrets.token_hex(6)
        self.client_secret = secrets.token_hex(20)
        self.code = secrets.token_hex(10)
        self.token = secrets.token_urlsafe(32)
        self.refresh = None
        self.expires_in = None
        self.challenge = None
        self.scope = SCOPES
        self.revoked = False
        self.registered = []
        self.requests: list[httpx.Request] = []

    def authorized(self, request) -> bool:
        return request.headers.get("authorization") == f"Bearer {self.token}" \
            and not self.revoked

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "hn.algolia.com":
            return httpx.Response(200, json={"hits": []})
        path = request.url.path
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} \
            if request.method == "POST" else {}
        if path == "/api/v1/apps":
            self.registered.append(form)
            return httpx.Response(200, json={"client_id": self.client_id,
                                             "client_secret": self.client_secret})
        if path == "/oauth/token":
            if form.get("grant_type") == "refresh_token":
                if form.get("refresh_token") != self.refresh:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.token = secrets.token_urlsafe(32)
                return httpx.Response(200, json={"access_token": self.token, "scope": SCOPES,
                                                 "expires_in": 3600})
            verifier = form.get("code_verifier", "")
            digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            if form.get("code") != self.code or digest.decode().rstrip("=") != self.challenge \
                    or form.get("client_secret") != self.client_secret:
                return httpx.Response(400, json={"error": "invalid_grant"})
            reply = {"access_token": self.token, "scope": self.scope, "token_type": "Bearer"}
            if self.refresh:
                reply.update(refresh_token=self.refresh, expires_in=self.expires_in)
            return httpx.Response(200, json=reply)
        if path == "/oauth/revoke":
            self.revoked = form.get("token") == self.token
            return httpx.Response(200, json={})
        if not self.authorized(request):
            return httpx.Response(401, json={"error": "The access token is invalid"})
        if path == "/api/v1/accounts/verify_credentials":
            return httpx.Response(200, json={"acct": "jo-example", "id": "1"})
        if path in ("/api/v1/timelines/home", "/api/v1/timelines/list/42"):
            return httpx.Response(200, json=[
                {"id": "1", "url": f"https://{INSTANCE}/@a/1", "content": "<p>A CRDT engine "
                 "for SQLite ships offline sync</p>", "created_at": "2026-09-23T10:00:00Z",
                 "account": {"acct": "someone"},
                 "card": {"url": "https://example.org/crdt", "title": "CRDTs"}},
                {"id": "2", "reblog": {"id": "3", "url": f"https://{INSTANCE}/@b/3",
                                       "content": "<p>Batteries and microgrids</p>",
                                       "created_at": "2026-09-23T11:00:00Z"}}])
        if path == "/api/v1/lists/42":
            return httpx.Response(200, json={"id": "42", "title": "Local-first people"})
        return httpx.Response(404)


def http_for(fake):
    return HTTP(transport=httpx.MockTransport(fake), resolver=lambda h: ["93.184.216.34"])


def connections(store, tmp_path, fake, machine_id):
    return Connections(store, tmp_path / "data", http_for(fake), machine_id=machine_id)


def connect(conns, fake, redirect="http://localhost:8765/connections/mastodon/callback"):
    url, state_id = conns.start("mastodon", INSTANCE, redirect)
    query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    fake.challenge = query["code_challenge"]
    return conns.finish("mastodon", str(state_id), {"state": query["state"], "code": fake.code})


# -- the vault ------------------------------------------------------------------------------


def test_vault_round_trips_encrypted_with_private_modes(tmp_path, machine_id):
    vault = Vault(tmp_path / "secrets", machine_id=machine_id)
    token = secrets.token_urlsafe(24)
    vault.put("conn:1", {"access_token": token})
    assert vault.get("conn:1") == {"access_token": token}
    assert token.encode() not in vault.path.read_bytes()
    assert stat.S_IMODE(vault.directory.stat().st_mode) == 0o700
    for path in (vault.path, vault.salt_path):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert vault.problems() == []
    vault.update("conn:1", last_used_at="now")
    assert vault.get("conn:1")["last_used_at"] == "now"
    vault.delete("conn:1")
    assert vault.get("conn:1") is None


def test_vault_refuses_another_machine_or_salt(tmp_path, machine_id):
    vault = Vault(tmp_path / "secrets", machine_id=machine_id)
    vault.put("conn:1", {"access_token": secrets.token_hex(8)})
    other = tmp_path / "other-id"
    other.write_text(secrets.token_hex(16))
    with pytest.raises(VaultError, match="another machine"):
        Vault(tmp_path / "secrets", machine_id=other).get("conn:1")
    vault.salt_path.write_bytes(secrets.token_bytes(32))
    with pytest.raises(VaultError, match="another machine or with another salt"):
        vault.get("conn:1")
    vault.salt_path.unlink()
    with pytest.raises(VaultError, match="salt"):
        vault.get("conn:1")


def _old_vault(directory, machine_id, entries):
    """A vault as the server before the rename wrote it (its own ``_write``): a random salt,
    the key from HKDF-SHA256 with its info, AES-256-GCM with its associated data."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    from kranto import legacy

    directory.mkdir(parents=True, mode=0o700)
    salt = secrets.token_bytes(32)
    (directory / "salt").write_bytes(salt)
    os.chmod(directory / "salt", 0o600)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=legacy.VAULT_INFO) \
        .derive(machine_id.read_text().strip().encode())
    nonce = secrets.token_bytes(12)
    data = AESGCM(key).encrypt(nonce, json.dumps(entries).encode(), legacy.VAULT_AAD)
    path = directory / "connections.json"
    path.write_text(json.dumps({"version": 1, "cipher": "AES-256-GCM",
                                "nonce": base64.b64encode(nonce).decode(),
                                "data": base64.b64encode(data).decode()}))
    os.chmod(path, 0o600)
    return path


def _opens_with(path, salt_path, machine_id, info, aad) -> bool:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    env = json.loads(path.read_text())
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt_path.read_bytes(), info=info) \
        .derive(machine_id.read_text().strip().encode())
    try:
        AESGCM(key).decrypt(base64.b64decode(env["nonce"]), base64.b64decode(env["data"]), aad)
    except InvalidTag:
        return False
    return True


def test_the_vault_labels_are_the_ones_each_version_wrote():
    """Kranto's own (the first Kranto releases wrote them: kept, odd wording and all) and the
    server's from before the rename, byte for byte."""
    from kranto import legacy
    from kranto.connections import vault as v

    old = "be" + "ars" + "afk"
    assert (v._INFO, v._AAD) == (b"the server connections v1", b"kranto-connections")
    want = (f"{old} connections v1".encode(), f"{old}-connections".encode())
    assert want == (legacy.VAULT_INFO, legacy.VAULT_AAD)
    assert v.LABELS == ((v._INFO, v._AAD), (legacy.VAULT_INFO, legacy.VAULT_AAD))


def test_a_vault_written_before_the_rename_reads_and_is_rewritten_at_the_next_write(
        tmp_path, machine_id):
    from kranto import legacy
    from kranto.connections import vault as v

    token, other = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    path = _old_vault(tmp_path / "secrets", machine_id,
                      {"conn:1": {"access_token": token, "last_used_at": None},
                       "conn:2": {"key": other}})
    before = path.read_bytes()
    vault = Vault(tmp_path / "secrets", machine_id=machine_id)
    assert vault.get("conn:1") == {"access_token": token, "last_used_at": None}
    assert vault.keys() == ["conn:1", "conn:2"] and vault.old_labels
    assert vault.problems() == []
    assert path.read_bytes() == before                 # reading never writes
    vault.update("conn:1", last_used_at="now")
    assert not vault.old_labels
    assert _opens_with(path, vault.salt_path, machine_id, v._INFO, v._AAD)
    assert not _opens_with(path, vault.salt_path, machine_id, legacy.VAULT_INFO,
                           legacy.VAULT_AAD)
    fresh = Vault(tmp_path / "secrets", machine_id=machine_id)
    assert fresh.get("conn:1") == {"access_token": token, "last_used_at": "now"}
    assert fresh.get("conn:2") == {"key": other} and not fresh.old_labels
    assert token.encode() not in path.read_bytes()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_vault_from_before_the_rename_on_another_machine_still_fails_in_todays_words(
        tmp_path, machine_id):
    path = _old_vault(tmp_path / "secrets", machine_id,
                      {"conn:1": {"access_token": secrets.token_urlsafe(24)}})
    before = path.read_bytes()
    other = tmp_path / "other-id"
    other.write_text(secrets.token_hex(16))
    vault = Vault(tmp_path / "secrets", machine_id=other)
    words = (f"{path} cannot be decrypted here: it was written on another machine or with "
             "another salt. Connect the accounts again.")
    with pytest.raises(VaultError) as got:
        vault.get("conn:1")
    assert str(got.value) == words
    assert vault.problems() == [words]
    # and nothing is written over it: a write reads first, and stops
    with pytest.raises(VaultError):
        vault.put("conn:9", {"key": secrets.token_hex(8)})
    assert path.read_bytes() == before


def test_vault_problems_name_loose_modes(tmp_path, machine_id):
    vault = Vault(tmp_path / "secrets", machine_id=machine_id)
    vault.put("k", {"v": 1})
    os.chmod(vault.path, 0o644)
    os.chmod(vault.directory, 0o755)
    problems = " ".join(vault.problems())
    assert "should be 600" in problems and "should be 700" in problems


def test_secret_never_prints_itself():
    value = secrets.token_hex(12)
    s = Secret(value)
    assert value not in f"{s} {s!r} {s:>10} {[s]} {dict(a=s)}"
    assert s.reveal() == value
    with pytest.raises(TypeError):
        __import__("pickle").dumps(s)


# -- with_auth --------------------------------------------------------------------------


class StaticAuth:
    def __init__(self, host, token):
        self.host, self.token, self.refusals = host, token, 0

    def headers(self, method, url):
        return {"Authorization": f"Bearer {self.token}"}

    def refused(self):
        self.refusals += 1


def test_with_auth_adds_the_header_only_for_its_host_and_never_in_the_url():
    token = secrets.token_urlsafe(20)
    seen = []

    def site(request):
        seen.append(request)
        if request.url.host == "a.example" and request.url.path == "/moved":
            return httpx.Response(302, headers={"location": "https://b.example/landing"})
        return httpx.Response(200, json={"ok": True})

    base = http_for(site)
    authed = base.with_auth(StaticAuth("a.example", token))
    authed.get_json("https://a.example/api")
    authed.get("https://a.example/moved")
    base.get("https://a.example/plain")
    assert seen[0].headers["authorization"] == f"Bearer {token}"
    assert seen[1].headers["authorization"] == f"Bearer {token}"
    assert "authorization" not in seen[2].headers, "a redirect elsewhere goes without it"
    assert "authorization" not in seen[3].headers, "the base client is unchanged"
    assert all(token not in str(r.url) for r in seen)
    authed.close()
    base.get("https://a.example/still-open")


def test_a_refused_token_is_needs_login_and_the_error_holds_no_token():
    token = secrets.token_urlsafe(20)
    auth = StaticAuth("a.example", token)
    authed = http_for(lambda r: httpx.Response(401)).with_auth(auth)
    with pytest.raises(SourceError) as info:
        authed.get("https://a.example/api")
    assert info.value.needs_login and info.value.transient and auth.refusals == 1
    assert token not in str(info.value)


def test_refresh_on_expiry_with_a_fake_transport(store, tmp_path, machine_id):
    fake = FakeMastodon()
    fake.refresh = secrets.token_urlsafe(16)
    fake.expires_in = 60  # inside the five-minute window: the first use refreshes it
    conns = connections(store, tmp_path, fake, machine_id)
    conn = connect(conns, fake)
    first = fake.token
    authed = conns.http_for("mastodon", INSTANCE, conns.http)
    authed.get_json(f"https://{INSTANCE}/api/v1/timelines/home")
    assert fake.token != first, "refreshed before the request"
    assert fake.requests[-1].headers["authorization"] == f"Bearer {fake.token}"
    # A refresh token the provider no longer accepts marks the connection Needs login.
    conns.vault.update(f"conn:{conn['id']}", expires_at=0, refresh_token="x" * 20)
    with pytest.raises(SourceError) as info:
        conns.http_for("mastodon", INSTANCE, conns.http).get(
            f"https://{INSTANCE}/api/v1/timelines/home")
    assert info.value.needs_login
    assert conns.current("mastodon", INSTANCE)["state"] == "needs_login"


# -- scrub ------------------------------------------------------------------------------------


@pytest.mark.parametrize("make", [
    lambda: "ya29." + secrets.token_urlsafe(40),
    lambda: "Authorization: Bearer " + secrets.token_urlsafe(30),
    lambda: "authorization=" + secrets.token_hex(20),
    lambda: "bearer " + secrets.token_urlsafe(30),
    lambda: "https://x.example/cb?client_secret=" + secrets.token_hex(16),
    lambda: "access_token=" + secrets.token_urlsafe(20),
    lambda: "refresh_token=" + secrets.token_urlsafe(20),
    lambda: "code_verifier=" + secrets.token_urlsafe(40),
    lambda: "-".join(["ab2c", "d3fg", "hi4j", "k5lm"]),
])
def test_scrub_catches_each_providers_token_form(make):
    text = make()
    secret_part = text.split("=")[-1].split(" ")[-1]
    out = scrub.scrub(f"failed: {text} (retry)")
    assert secret_part not in out and "[secret]" in out


def test_scrub_leaves_ordinary_hyphenated_words():
    assert scrub.scrub("how to self-host-your-data at home") == \
        "how to self-host-your-data at home"


# -- state and PKCE ----------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path, machine_id):
    return Vault(tmp_path / "secrets", machine_id=machine_id)


def test_pkce_pair_is_s256():
    verifier, challenge = oauth.pkce_pair()
    assert 43 <= len(verifier) <= 128
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    assert digest.decode().rstrip("=") == challenge


def test_callback_state_is_checked_and_spent(store, vault):
    started = oauth.start(store, vault, "mastodon", INSTANCE, "http://localhost:1/cb")
    row = store.query_one("SELECT * FROM oauth_states")
    assert started.state not in json.dumps(dict(row)), "only a hash of the state is stored"
    with pytest.raises(OAuthError, match="no state"):
        oauth.consume(store, vault, "mastodon", None, started.state)
    with pytest.raises(OAuthError, match="not one the server started"):
        oauth.consume(store, vault, "github", str(started.state_id), started.state)
    with pytest.raises(OAuthError, match="does not match"):
        oauth.consume(store, vault, "mastodon", str(started.state_id), "x" + started.state)
    with pytest.raises(OAuthError, match="already used"):
        oauth.consume(store, vault, "mastodon", str(started.state_id), started.state)


def test_a_good_state_passes_once_and_an_expired_one_never(store, vault):
    good = oauth.start(store, vault, "mastodon", INSTANCE, "http://localhost:1/cb")
    pending = oauth.consume(store, vault, "mastodon", str(good.state_id), good.state)
    assert pending.instance == INSTANCE and pending.verifier
    assert vault.get(f"oauth:{good.state_id}") is None, "the verifier is used once"
    old = oauth.start(store, vault, "mastodon", INSTANCE, "http://localhost:1/cb",
                      now=utcnow() - timedelta(minutes=11))
    with pytest.raises(OAuthError, match="10 minutes"):
        oauth.consume(store, vault, "mastodon", str(old.state_id), old.state)
    stale = oauth.start(store, vault, "mastodon", INSTANCE, "http://localhost:1/cb",
                        now=utcnow() - timedelta(hours=2))
    assert oauth.cleanup(store, vault) >= 1
    assert store.query_one("SELECT 1 FROM oauth_states WHERE id = ?", (stale.state_id,)) is None
    assert vault.get(f"oauth:{stale.state_id}") is None


# -- Mastodon against a fake instance ---------------------------------------------------------


def test_mastodon_flow_registers_once_asks_read_only_and_labels_the_account(
        store, tmp_path, machine_id):
    fake = FakeMastodon()
    conns = connections(store, tmp_path, fake, machine_id)
    redirect = "http://localhost:8765/connections/mastodon/callback"
    url, _ = conns.start("mastodon", f"https://{INSTANCE}/", redirect)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == INSTANCE and parsed.path == "/oauth/authorize"
    assert query["redirect_uri"] == [redirect] and query["scope"] == [SCOPES]
    assert query["code_challenge_method"] == ["S256"] and query["state"][0]
    assert fake.registered[0]["redirect_uris"] == redirect
    assert fake.registered[0]["scopes"] == SCOPES
    conn = connect(conns, fake, redirect)
    assert len(fake.registered) == 1, "one app per instance and callback"
    assert conn["account"] == f"@jo-example@{INSTANCE}" and conn["state"] == "connected"
    assert json.loads(conn["scopes"]) == SCOPES.split()
    [account] = conns.accounts()
    assert account["account"] == f"@jo-example@{INSTANCE}" and len(account["scopes"]) == 3
    assert conns.test(conn["id"])["ok"]


def test_a_grant_wider_than_read_only_is_revoked_and_refused(store, tmp_path, machine_id):
    fake = FakeMastodon()
    fake.scope = SCOPES + " write:statuses"
    conns = connections(store, tmp_path, fake, machine_id)
    with pytest.raises(OAuthError, match="more than read-only"):
        connect(conns, fake)
    assert fake.revoked and conns.accounts() == []


def test_a_declined_or_replayed_callback_connects_nothing(store, tmp_path, machine_id):
    fake = FakeMastodon()
    conns = connections(store, tmp_path, fake, machine_id)
    url, state_id = conns.start("mastodon", INSTANCE, "http://localhost:1/cb")
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(OAuthError, match="not granted"):
        conns.finish("mastodon", str(state_id), {"state": state, "error": "access_denied"})
    with pytest.raises(OAuthError, match="already used"):
        conns.finish("mastodon", str(state_id), {"state": state, "code": fake.code})
    assert conns.accounts() == []


def test_disconnect_revokes_and_deletes(store, tmp_path, machine_id):
    fake = FakeMastodon()
    conns = connections(store, tmp_path, fake, machine_id)
    conn = connect(conns, fake)
    note = conns.disconnect(conn["id"])
    assert "revoked" in note and fake.revoked
    assert conns.vault.get(f"conn:{conn['id']}") is None and conns.accounts() == []
    with pytest.raises(SourceError) as info:
        conns.http_for("mastodon", INSTANCE, conns.http)
    assert info.value.needs_login


def test_reconnecting_replaces_the_old_connection(store, tmp_path, machine_id):
    fake = FakeMastodon()
    conns = connections(store, tmp_path, fake, machine_id)
    first = connect(conns, fake)
    fake.token = secrets.token_urlsafe(32)
    fake.revoked = False
    second = connect(conns, fake)
    assert [a["id"] for a in conns.accounts()] == [second["id"]]
    assert conns.get(first["id"])["state"] == "disconnected"


# -- ingest, the web flow, and where a token must never be ---------------------------------------


def judge_reply(body):
    if "first, quick look" in body["messages"][0]["content"]:
        return chat_response(json.dumps({"pass": True, "reason": "ok"}))
    return chat_response(json.dumps({
        "kind": "beat", "summary": "s", "why_it_matters": "w", "content_quality": 0.9,
        "durability": 0.9, "opportunity": 0.9, "override": False, "tags": ["t"]}))


@pytest.fixture
def rig(tmp_path, embedder, make_client, machine_id):
    fake = FakeMastodon()
    store = Store.open(tmp_path / "data" / "kranto.db")
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(fetch_full_text=False), map=MapConfig(),
                 look=LookConfig(enabled=False))
    http = http_for(fake)
    conns = Connections(store, cfg.data_dir, http, machine_id=machine_id)
    from kranto.llm import LLMClient

    client = LLMClient(store, cfg.llm, cfg.budget, api_key="k",
                       transport=httpx.MockTransport(
                           lambda r: judge_reply(json.loads(r.content))))
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=client, http=http,
                      connections=conns)
    yield rt, fake
    rt.close()


def test_web_flow_end_to_end_then_ingest_then_revoked_token_needs_login(rig, caplog):
    rt, fake = rig
    caplog.set_level(logging.DEBUG)
    with web_client(create_app(rt), "http://localhost:8765") as web:
        start = web.post("/connections/mastodon/start", json={"instance": INSTANCE})
        assert start.status_code == 200, start.text
        url = start.json()["authorize_url"]
        assert start.json()["callback"] == "http://localhost:8765/connections/mastodon/callback"
        cookie = start.cookies.get("afk_oauth")
        assert cookie and "httponly" in start.headers["set-cookie"].lower()
        assert "samesite=lax" in start.headers["set-cookie"].lower()
        query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        fake.challenge = query["code_challenge"]
        # A callback without the cookie is refused, and spends the state.
        bare = web_client(create_app(rt), "http://localhost:8765")
        refused = bare.get("/connections/mastodon/callback", params={
            "state": query["state"], "code": fake.code}, follow_redirects=False)
        assert "Not+connected" in refused.headers["location"]
        assert rt.connections.accounts() == []

        start = web.post("/connections/mastodon/start", json={"instance": INSTANCE})
        query = {k: v[0] for k, v in parse_qs(urlparse(start.json()["authorize_url"])
                                               .query).items()}
        fake.challenge = query["code_challenge"]
        done = web.get("/connections/mastodon/callback",
                       params={"state": query["state"], "code": fake.code},
                       follow_redirects=False)
        assert done.status_code == 303 and "Connected" in done.headers["location"]
        [account] = web.get("/api/connections").json()["accounts"]
        assert account["account"] == f"@jo-example@{INSTANCE}"

        # A source from the catalog's login preset, previewed then added.
        body = {"preset": "mastodon.home", "fields": {"instance": INSTANCE}}
        preview = web.post("/api/sources/preview", json=body).json()
        assert preview["items"] == 2 and preview["kind"] == "mastodon"
        added = web.post("/api/sources", json=body).json()
        assert added["status"] == "approved"
        listed = web.post("/api/sources/preview", json={
            "preset": "mastodon.list", "fields": {"instance": INSTANCE, "list": "42"}}).json()
        assert listed["label"] == f"Your list Local-first people on {INSTANCE}"

        report = run_ingest(rt.cfg, rt.store, rt.llm, rt.embedder, rt.http,
                            connections=rt.connections, lock_path=rt.cfg.data_dir / "l.lock")
        assert report.status == "ok" and report.contributed == 2
        assert report.sources[0].fetch_state == "ok"

        # The token is revoked on the instance: the next run marks the source and the
        # connection Needs login, and goes on.
        fake.revoked = True
        library.add_source(rt.store, "hackernews", {"feed": "front"}, label="HN")
        report = run_ingest(rt.cfg, rt.store, rt.llm, rt.embedder, rt.http,
                            connections=rt.connections, lock_path=rt.cfg.data_dir / "l.lock")
        masto = next(s for s in report.sources if s.source_id == added["id"])
        assert masto.fetch_state == "needs_login" and "refused" in masto.fetch_error
        assert report.status == "degraded"
        row = next(s for s in web.get("/api/sources").json()["sources"]
                   if s["id"] == added["id"])
        assert row["status"] == "needs_login"
        assert web.get("/api/sources").json()["connections_need_you"] == 1
        assert web.get("/api/connections").json()["accounts"][0]["state"] == "needs_login"

        pages = [web.get(p).text for p in ("/api/connections", "/api/sources",
                                           f"/api/sources/{added['id']}", "/connections",
                                           "/api/catalog", "/topics")]
        assert web.post(f"/api/connections/{account['id']}/disconnect").json()["ok"]

    secrets_now = [fake.token, fake.client_secret, fake.code]
    # Not in a page or an API response.
    for text in pages:
        for s in secrets_now:
            assert s not in text
    # Not in the log, at DEBUG, httpx's own loggers included. The test client's own
    # lines are the browser's side (its callback URL carries the one-time code).
    server_log = "\n".join(r.getMessage() for r in caplog.records
                           if "localhost:8765" not in r.getMessage())
    for s in secrets_now:
        assert s not in server_log
    # Not in the library database, its WAL, or any export.
    rt.store.query("PRAGMA wal_checkpoint(FULL)")
    db_bytes = b"".join(p.read_bytes() for p in rt.cfg.data_dir.glob("kranto.db*"))
    out = io.StringIO()
    for table in rt.store.append_only_tables() + ["settings"]:
        rt.store.export_jsonl(table, out)
    events = json.dumps([dict(r) for r in rt.store.query("SELECT * FROM connection_events")])
    for s in secrets_now:
        assert s.encode() not in db_bytes
        assert s not in out.getvalue() and s not in events
    # Not readable in the vault file either: it is encrypted.
    raw = (rt.cfg.data_dir / "secrets" / "connections.json").read_bytes()
    assert all(s.encode() not in raw for s in secrets_now)


def test_sign_in_needs_a_loopback_host_name(rig):
    rt, _ = rig
    app = create_app(rt, allowed_hosts={"localhost", "127.0.0.1", "host.lan"})
    with web_client(app, "http://host.lan:8765") as web:
        r = web.post("/connections/mastodon/start", json={"instance": INSTANCE})
    assert r.status_code == 400 and "localhost" in r.json()["error"]


def test_the_plain_form_flow_offers_a_link(rig):
    rt, fake = rig
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        page = web.post("/connections/mastodon/start", data={"instance": INSTANCE})
        assert page.status_code == 200 and "Continue to sign in" in page.text
        assert f"https://{INSTANCE}/oauth/authorize?" in page.text
        assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8765" in page.text
        listing = web.get("/connections")
        assert "Mastodon" in listing.text and "Reddit" in listing.text


def test_doctor_reports_secrets_and_needs_login(rig, machine_id, monkeypatch):
    from kranto import doctor

    rt, fake = rig
    connect(rt.connections, fake)
    checks = {c.name: c for c in doctor._connections(rt.cfg, rt.store, machine_id=machine_id)}
    assert checks["secrets"].status == doctor.OK
    assert checks["connections"].status == doctor.OK
    rt.connections.mark_needs_login(rt.connections.accounts()[0]["id"], "test")
    os.chmod(rt.cfg.data_dir / "secrets" / "connections.json", 0o644)
    checks = {c.name: c for c in doctor._connections(rt.cfg, rt.store, machine_id=machine_id)}
    assert checks["secrets"].status == doctor.FAIL and "600" in checks["secrets"].detail
    assert checks["connections"].status == doctor.WARN
    assert "needs login" in checks["connections"].detail


def test_doctor_is_ok_with_a_vault_written_before_the_rename(rig, machine_id):
    """An install that crossed over keeps its connected accounts: the doctor's secrets line is
    ok, the account is listed, and its token is used."""
    from kranto import doctor

    rt, fake = rig
    connect(rt.connections, fake)
    vault = rt.connections.vault
    entries = vault._read()
    import shutil
    shutil.rmtree(vault.directory)
    _old_vault(vault.directory, machine_id, entries)
    checks = {c.name: c for c in doctor._connections(rt.cfg, rt.store, machine_id=machine_id)}
    assert checks["secrets"].status == doctor.OK, checks["secrets"].detail
    assert "readable here" in checks["secrets"].detail
    assert "before the rename" in checks["secrets"].detail
    assert checks["connections"].status == doctor.OK
    assert "jo-example" in checks["connections"].detail
    [account] = rt.connections.accounts()
    assert account["state"] == "connected"
    assert rt.connections.test(account["id"])["ok"] is True
    checks = {c.name: c for c in doctor._connections(rt.cfg, rt.store, machine_id=machine_id)}
    assert checks["secrets"].status == doctor.OK
    assert "before the rename" not in checks["secrets"].detail   # rewritten by the use


def test_connection_rows_hold_no_secret_columns(store):
    cols = {r["name"] for t in ("connections", "connection_events", "oauth_states")
            for r in store.query(f"PRAGMA table_info({t})")}
    assert not cols & {"token", "access_token", "refresh_token", "client_secret", "verifier",
                       "state", "code"}
    assert "oauth_states" not in store.append_only_tables()
    assert {"connections", "connection_events", "source_fetches"} <= \
        set(store.append_only_tables())
    store.insert("connections", {"provider": "mastodon", "instance": INSTANCE, "account": "@a",
                                 "scopes": "[]", "created_at": iso(utcnow())})
    with pytest.raises(Exception, match="append-only"):
        store.query("UPDATE connections SET account = 'x'")
