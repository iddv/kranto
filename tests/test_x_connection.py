"""X as a connection: the person's own Native App, PKCE S256 on 127.0.0.1, a
public client (no secret), read-only scopes, refresh tokens that rotate (refreshed under the
vault's file lock, so two processes never both spend one), revoke on Disconnect, and no token
anywhere it must not be. Against ``tests/fake_x.py``; nothing reaches X."""

import io
import json
import logging
import os
import secrets
import threading
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from kranto.config import BudgetConfig, Config, IngestConfig, LookConfig, MapConfig
from kranto.connections import INFO, Connections, OAuthError
from kranto.runtime import open_runtime
from kranto.sources import HTTP, SourceError
from kranto.store import Store
from kranto.web.app import create_app

from .conftest import llm_config, web_client
from .fake_x import SCOPES, USER_ID, FakeX

CALLBACK = "http://127.0.0.1:8765/connections/x/callback"


@pytest.fixture
def machine_id(tmp_path):
    path = tmp_path / "machine-id"
    path.write_text(secrets.token_hex(16) + "\n")
    return path


def http_for(fake):
    return HTTP(transport=httpx.MockTransport(fake), resolver=lambda h: ["93.184.216.34"])


def conns_for(store, tmp_path, fake, machine_id):
    return Connections(store, tmp_path / "data", http_for(fake), machine_id=machine_id)


def sign_in(conns, fake, redirect=CALLBACK):
    url, state_id = conns.start("x", "", redirect)
    query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    fake.authorized_with(query, redirect)
    return conns.finish("x", str(state_id), {"state": query["state"], "code": fake.code}), query


@pytest.fixture
def x(store, tmp_path, machine_id):
    fake = FakeX()
    conns = conns_for(store, tmp_path, fake, machine_id)
    conns.set_client("x", {"client_id": fake.client_id})
    return conns, fake


def test_the_page_lists_x_as_a_client_flow_with_its_steps_and_cost():
    p = INFO["x"]
    assert p["state"] == "available" and p["flow"] == "client"
    assert p["redirect_host"] == "127.0.0.1"
    assert p["client_section"] == "1. Your X developer app"
    assert [f["key"] for f in p["fields"]] == ["client_id"]
    assert not any(f.get("secret") for f in p["fields"])
    assert "Native App" in " ".join(p["steps"]) and "spending limit" in " ".join(p["steps"])
    assert "$0.005" in p["blurb"] and "$46" in p["cost"]
    assert set(p["scopes"]) == set(SCOPES.split())


def test_the_client_id_is_checked_kept_and_removed(store, tmp_path, machine_id):
    conns = conns_for(store, tmp_path, FakeX(), machine_id)
    with pytest.raises(OAuthError, match="paste your X app's client id"):
        conns.start("x", "", CALLBACK)
    with pytest.raises(OAuthError, match="not an X OAuth 2.0 client id"):
        conns.set_client("x", {"client_id": "has spaces in it"})
    conns.set_client("x", {"client_id": "abc" + secrets.token_urlsafe(20)})
    info = next(p for p in conns.provider_info() if p["key"] == "x")
    assert info["client_set"] is True
    conns.clear_client("x")
    assert next(p for p in conns.provider_info() if p["key"] == "x")["client_set"] is False


def test_sign_in_is_pkce_s256_read_only_and_labels_the_account(x):
    conns, fake = x
    conn, query = sign_in(conns, fake)
    assert query["code_challenge_method"] == "S256" and query["client_id"] == fake.client_id
    assert query["redirect_uri"] == CALLBACK and query["response_type"] == "code"
    assert query["scope"].split() == SCOPES.split()
    assert conn["account"] == "@reader" and conn["state"] == "connected"
    token = next(r for r in fake.requests if r.url.path == "/2/oauth2/token")
    # a public client: no secret, no Basic header, the client id in the body
    assert "authorization" not in token.headers
    assert parse_qs(token.content.decode())["client_id"] == [fake.client_id]
    entry = conns.vault.get(f"conn:{conn['id']}")
    assert entry["user_id"] == USER_ID and entry["refresh_token"] == fake.refresh_token
    assert entry["via"] == "oauth" and entry["expires_at"] > 0
    assert set(json.loads(conn["scopes"])) == set(SCOPES.split())


def test_a_wider_grant_is_revoked_and_refused(x):
    conns, fake = x
    fake.scope = SCOPES + " tweet.write dm.read"
    with pytest.raises(OAuthError, match="more than read-only"):
        sign_in(conns, fake)
    assert fake.access in fake.revoked and fake.refresh_token in fake.revoked
    assert conns.accounts() == []


def test_a_grant_without_a_refresh_token_is_refused(x):
    conns, fake = x
    fake.give_refresh = False
    with pytest.raises(OAuthError, match="no refresh token"):
        sign_in(conns, fake)
    assert fake.access in fake.revoked and conns.accounts() == []


def test_a_replayed_or_declined_callback_connects_nothing(x):
    conns, fake = x
    url, state_id = conns.start("x", "", CALLBACK)
    query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    fake.authorized_with(query, CALLBACK)
    with pytest.raises(OAuthError, match="not granted"):
        conns.finish("x", str(state_id), {"state": query["state"], "error": "access_denied"})
    with pytest.raises(OAuthError, match="already used"):
        conns.finish("x", str(state_id), {"state": query["state"], "code": fake.code})
    assert conns.accounts() == []


def expire(conns, conn_id):
    conns.vault.update(f"conn:{conn_id}", expires_at=conns.clock() + 10)


def test_refresh_rotates_the_pair_and_the_old_refresh_token_is_dead(x):
    conns, fake = x
    conn, _ = sign_in(conns, fake)
    old_refresh, old_access = fake.refresh_token, fake.access
    expire(conns, conn["id"])
    entry = conns.credentials(conn["id"])
    assert entry["access_token"] == fake.access != old_access
    assert entry["refresh_token"] == fake.refresh_token != old_refresh
    assert old_refresh in fake.spent_refresh
    stored = conns.vault.get(f"conn:{conn['id']}")
    assert stored["refresh_token"] == fake.refresh_token and stored["user_id"] == USER_ID


def test_two_processes_refreshing_at_once_spend_the_token_once(store, tmp_path, machine_id):
    """``python -m kranto serve`` and a cron ``python -m kranto run``: two registries on one vault,
    each with its own
    file descriptor, refresh the same expired token at the same moment."""
    fake = FakeX()
    serve = conns_for(store, tmp_path, fake, machine_id)
    serve.set_client("x", {"client_id": fake.client_id})
    conn, _ = sign_in(serve, fake)
    cron = conns_for(store, tmp_path, fake, machine_id)
    expire(serve, conn["id"])
    got, errors = [], []

    def run(c):
        try:
            got.append(c.credentials(conn["id"])["access_token"])
        except SourceError as exc:          # pragma: no cover - the failure being guarded
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(c,)) for c in (serve, cron, serve, cron)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    refreshes = [r for r in fake.requests if r.url.path == "/2/oauth2/token"
                 and b"refresh_token" in r.content]
    assert errors == [] and len(refreshes) == 1
    assert set(got) == {fake.access}
    assert serve.accounts()[0]["state"] == "connected"


def test_a_refused_refresh_is_needs_login(x):
    conns, fake = x
    conn, _ = sign_in(conns, fake)
    fake.spent_refresh.add(fake.refresh_token)         # X no longer takes it
    expire(conns, conn["id"])
    with pytest.raises(SourceError) as err:
        conns.credentials(conn["id"])
    assert err.value.needs_login
    assert conns.accounts()[0]["state"] == "needs_login"


def test_the_vault_lock_is_reentrant_in_its_thread(tmp_path, machine_id):
    from kranto.connections.vault import Vault

    vault = Vault(tmp_path / "secrets", machine_id=machine_id)
    with vault.locked():
        vault.put("a", {"v": 1})
        with vault.locked():
            assert vault.update("a", v=2) == {"v": 2}
    assert vault.get("a") == {"v": 2}


def test_test_is_one_identity_call_and_disconnect_revokes_both_tokens(x):
    conns, fake = x
    conn, _ = sign_in(conns, fake)
    before = len(fake.requests)
    assert conns.test(conn["id"]) == {"ok": True, "message": "Signed in as @reader, 6 "
                                                             "read-only scopes."}
    assert [r.url.path for r in fake.requests[before:]] == ["/2/users/me"]
    access, refresh = fake.access, fake.refresh_token
    note = conns.disconnect(conn["id"])
    assert note == "revoked at the provider and deleted here"
    assert {access, refresh} <= fake.revoked
    revokes = [parse_qs(r.content.decode()) for r in fake.requests
               if r.url.path == "/2/oauth2/revoke"]
    assert [r["token_type_hint"] for r in revokes] == [["refresh_token"], ["access_token"]]
    assert all(r["client_id"] == [fake.client_id] for r in revokes)
    assert conns.vault.get(f"conn:{conn['id']}") is None and conns.accounts() == []


def test_the_token_is_added_at_send_time_only_for_api_x_com(x):
    conns, fake = x
    sign_in(conns, fake)
    authed = conns.http_for("x", None, http_for(fake))
    assert authed.auth_host == "api.x.com"
    authed.get_json("https://api.x.com/2/users/me")
    assert fake.requests[-1].headers["authorization"] == f"Bearer {fake.access}"
    assert fake.access not in str(fake.requests[-1].url)


# -- the browser flow, end to end, and the canaries ------------------------------------------


@pytest.fixture
def rig(tmp_path, embedder, machine_id):
    from kranto.llm import LLMClient

    fake = FakeX()
    store = Store.open(tmp_path / "data" / "kranto.db")
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=None),
                 ingest=IngestConfig(fetch_full_text=False), map=MapConfig(),
                 look=LookConfig(enabled=False))
    http = http_for(fake)
    conns = Connections(store, cfg.data_dir, http, machine_id=machine_id)
    llm = LLMClient(store, cfg.llm, cfg.budget, api_key="k",
                    transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=llm, http=http,
                      connections=conns)
    yield rt, fake
    rt.close()


def test_x_signs_in_from_127_0_0_1_only(rig):
    rt, fake = rig
    with web_client(create_app(rt), "http://localhost:8765") as web:
        assert web.post("/api/connections/x/credentials",
                        json={"client_id": fake.client_id}).json()["ok"]
        r = web.post("/connections/x/start", json={})
    assert r.status_code == 400 and "127.0.0.1" in r.json()["error"]


def test_web_flow_end_to_end_keeps_every_secret_out_of_sight(rig, caplog):
    rt, fake = rig
    caplog.set_level(logging.DEBUG)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        providers = web.get("/api/connections").json()["providers"]
        assert next(p for p in providers if p["key"] == "x")["client_set"] is False
        saved = web.post("/api/connections/x/credentials", json={"client_id": fake.client_id})
        assert saved.json() == {"ok": True, "message": "Saved. Now click Connect."}
        start = web.post("/connections/x/start", json={})
        assert start.status_code == 200, start.text
        assert start.json()["callback"] == CALLBACK
        url = start.json()["authorize_url"]
        assert url.startswith("https://x.com/i/oauth2/authorize?")
        query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        fake.authorized_with(query, CALLBACK)
        code = fake.code
        done = web.get("/connections/x/callback", params={"state": query["state"], "code": code},
                       follow_redirects=False)
        assert done.status_code == 303 and "Connected" in done.headers["location"]
        [account] = web.get("/api/connections").json()["accounts"]
        assert account["account"] == "@reader" and account["provider_name"] == "X / Twitter"
        assert web.post(f"/api/connections/{account['id']}/test").json()["ok"]
        verifier = next(parse_qs(r.content.decode())["code_verifier"][0] for r in fake.requests
                        if r.url.path == "/2/oauth2/token")
        access, refresh = fake.access, fake.refresh_token
        pages = [web.get(p).text for p in ("/api/connections", "/connections", "/api/catalog",
                                           "/api/sources")]
        removed = web.post("/api/connections/x/credentials", json={"clear": True}).json()
        assert removed["message"] == "Removed the client id."
        assert web.post(f"/api/connections/{account['id']}/disconnect").json()["ok"]

    canaries = {"access": access, "refresh": refresh, "code": code, "verifier": verifier}
    for text in pages:
        for name, value in canaries.items():
            assert value not in text, name
    server_log = "\n".join(r.getMessage() for r in caplog.records
                           if "127.0.0.1:8765" not in r.getMessage())
    for name, value in canaries.items():
        assert value not in server_log, name
    rt.store.query("PRAGMA wal_checkpoint(FULL)")
    db = b"".join(p.read_bytes() for p in rt.cfg.data_dir.glob("kranto.db*"))
    out = io.StringIO()
    for table in rt.store.append_only_tables() + ["settings"]:
        rt.store.export_jsonl(table, out)
    raw = (rt.cfg.data_dir / "secrets" / "connections.json").read_bytes()
    for name, value in canaries.items():
        assert value.encode() not in db and value not in out.getvalue(), name
        assert value.encode() not in raw, name
        # never in this process's environment, so never in anything it starts
        assert all(value not in v for v in os.environ.values()), name
