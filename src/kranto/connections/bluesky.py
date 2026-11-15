"""Bluesky: AT Protocol OAuth as a loopback client, with DPoP; or an app password.

**OAuth** (the default). Nothing is registered: the server is a loopback client
whose ``client_id`` is ``http://localhost`` with its redirect and scopes in the
query, as the AT Protocol OAuth profile allows for software on the person's own
machine. The redirect is ``http://127.0.0.1:<port>/connections/bluesky/callback``
(loopback clients must use an IP address), carried by the SSH tunnel.

1. The handle is resolved to a DID, the DID document to the account's PDS, the
   PDS to its authorization server (``/.well-known/oauth-protected-resource``,
   then ``/.well-known/oauth-authorization-server``). The handle must be listed
   in the DID document, both ways.
2. A pushed authorization request (PAR) with PKCE S256, the state, the scopes
   and a DPoP proof from a P-256 key made for this connection; the browser goes
   to the authorize endpoint with the returned ``request_uri``.
3. The callback (state checked first, ``iss`` checked) exchanges the code with
   the verifier and a DPoP proof. The token must be for the DID that was
   resolved, and its scopes must be the read calls asked for: a grant with
   ``transition:generic``, ``repo:``, ``blob:`` or anything else is revoked and
   refused.

Scopes, fixed in code: ``atproto`` plus ``rpc:`` permissions for four read
calls on the Bluesky AppView (``getTimeline``, ``searchPosts``, ``getFeed``,
``getListFeed``). Requests go to the PDS, which proxies them to the AppView
(``atproto-proxy``), with ``Authorization: DPoP`` and a fresh proof bound to
the method, the URL, the server's nonce and the token. Tokens are refreshed
with DPoP; Disconnect revokes at the authorization server.

**An app password** (the fallback, for a PDS without loopback OAuth). The
handle and an app password are used once with ``createSession``; only the
session's tokens are kept, never the password. An app password is not limited
by scopes, so the page says so: the server only ever calls the read endpoints
above. Disconnect ends the session (``deleteSession``); the app password itself
is revoked in Bluesky's settings.

https://atproto.com/specs/oauth · https://atproto.com/guides/permission-requests
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from urllib.parse import quote, urlencode, urlparse

import httpx

from ..sources.base import HTTP, SourceError
from . import dpop
from .base import Grant, Provider, need, status_of
from .oauth import OAuthError, Pending

log = logging.getLogger(__name__)

APPVIEW = "did:web:api.bsky.app#bsky_appview"
PROXY = {"atproto-proxy": APPVIEW}
READ_CALLS = ("app.bsky.feed.getTimeline", "app.bsky.feed.searchPosts", "app.bsky.feed.getFeed",
              "app.bsky.feed.getListFeed")
SCOPES = ("atproto",) + tuple(f"rpc:{call}?aud={quote(APPVIEW, safe=':')}"
                              for call in READ_CALLS)
PUBLIC_API = "https://public.api.bsky.app/xrpc"
PLC = "https://plc.directory"
_HANDLE = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


def clean_handle(value: str) -> str:
    handle = re.sub(r"^https?://bsky\.app/profile/", "", str(value or "").strip().lower())
    handle = handle.split("/")[0].lstrip("@")
    if not _HANDLE.fullmatch(handle):
        # The value is not echoed: a password pasted into the wrong box would
        # otherwise end up on the page and in the redirect URL.
        raise OAuthError("not a Bluesky handle such as name.bsky.social")
    return handle


def _jwt_claims(token: str) -> dict:
    """A session JWT's claims (read, not verified: the PDS verifies it)."""
    try:
        payload = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _jwt_exp(token: str) -> float | None:
    """The ``exp`` of a session JWT."""
    try:
        return float(_jwt_claims(token)["exp"])
    except (KeyError, ValueError, TypeError):
        return None


# The session scope of a plain app password. The account password gives
# ``com.atproto.access`` and an app password with DM access
# ``com.atproto.appPassPrivileged``; both are refused.
APP_PASS_SCOPE = "com.atproto.appPass"


class BlueskyProvider(Provider):
    key = "bluesky"
    name = "Bluesky"
    scopes = SCOPES
    default_instance = "bsky.app"
    browser = True
    redirect_host = "127.0.0.1"

    def __init__(self, http: HTTP, conns=None) -> None:
        super().__init__(http, conns)
        # The latest DPoP nonce each server sent (authorization server and PDS).
        self._nonces: dict[str, str] = {}

    def api_host(self, instance: str, entry: dict) -> str:
        return urlparse(entry.get("pds") or "").hostname or ""

    # -- resolving an account ----------------------------------------------------------

    def resolve(self, handle: str) -> dict:
        """``{did, handle, pds}`` for a handle, checked both ways."""
        data = self._get(f"{PUBLIC_API}/com.atproto.identity.resolveHandle",
                         {"handle": handle}, f"resolve {handle}")
        did = data.get("did")
        if not isinstance(did, str) or not re.fullmatch(r"did:(plc|web):[A-Za-z0-9._:%-]{3,200}",
                                                        did):
            raise OAuthError(f"Bluesky did not resolve {handle} to an account")
        if did.startswith("did:plc:"):
            doc = self._get(f"{PLC}/{did}", None, "read the account's DID document")
        else:
            doc = self._get(f"https://{did.removeprefix('did:web:')}/.well-known/did.json",
                            None, "read the account's DID document")
        if f"at://{handle}" not in (doc.get("alsoKnownAs") or []):
            raise OAuthError(f"the account's DID document does not list {handle}")
        pds = next((s.get("serviceEndpoint") for s in doc.get("service") or []
                    if isinstance(s, dict) and str(s.get("id", "")).endswith("#atproto_pds")),
                   None)
        if not isinstance(pds, str) or not pds.startswith("https://"):
            raise OAuthError("the account's DID document names no https PDS")
        return {"did": did, "handle": handle, "pds": pds.rstrip("/")}

    def _server(self, pds: str) -> dict:
        """The authorization server's metadata for a PDS."""
        resource = self._get(f"{pds}/.well-known/oauth-protected-resource", None,
                             "find the account's sign-in server")
        servers = resource.get("authorization_servers") or []
        issuer = servers[0] if servers and isinstance(servers[0], str) else None
        if not issuer or not issuer.startswith("https://"):
            raise OAuthError("the PDS names no https sign-in server")
        meta = self._get(f"{issuer.rstrip('/')}/.well-known/oauth-authorization-server", None,
                         "read the sign-in server's metadata")
        if meta.get("issuer") != issuer:
            raise OAuthError("the sign-in server's metadata names another issuer")
        for name in ("pushed_authorization_request_endpoint", "authorization_endpoint",
                     "token_endpoint"):
            if not str(meta.get(name) or "").startswith("https://"):
                raise OAuthError(f"the sign-in server has no https {name.replace('_', ' ')}")
        if "ES256" not in (meta.get("dpop_signing_alg_values_supported") or ["ES256"]):
            raise OAuthError("the sign-in server does not accept ES256 DPoP keys")
        return meta

    # -- OAuth ------------------------------------------------------------------------------

    @staticmethod
    def client_id(redirect_uri: str) -> str:
        return "http://localhost?" + urlencode({"redirect_uri": redirect_uri,
                                                "scope": " ".join(SCOPES)})

    def authorize(self, instance: str, value: str, redirect_uri: str, state: str,
                  challenge: str) -> tuple[str, dict]:
        who = self.resolve(clean_handle(value))
        meta = self._server(who["pds"])
        key = dpop.new_key()
        client_id = self.client_id(redirect_uri)
        reply = self._as_post(meta["pushed_authorization_request_endpoint"], {
            "client_id": client_id, "response_type": "code", "code_challenge": challenge,
            "code_challenge_method": "S256", "state": state, "redirect_uri": redirect_uri,
            "scope": " ".join(SCOPES), "login_hint": who["handle"]}, key,
            "start the sign-in", ok=(200, 201))
        request_uri = reply.get("request_uri")
        if not isinstance(request_uri, str) or not request_uri:
            raise OAuthError("the sign-in server returned no request URI")
        url = meta["authorization_endpoint"] + "?" + urlencode(
            {"client_id": client_id, "request_uri": request_uri})
        return url, {**who, "dpop_key": key, "issuer": meta["issuer"],
                     "token_endpoint": meta["token_endpoint"],
                     "revocation_endpoint": meta.get("revocation_endpoint"),
                     "client_id": client_id}

    def complete(self, pending: Pending, query: dict) -> Grant:
        x = pending.extra
        if not x.get("dpop_key"):
            raise OAuthError("the sign-in's key is gone; start again from Connections")
        # Required by the AT Protocol OAuth profile (RFC 9207), so a missing
        # ``iss`` is refused as well as another one.
        if query.get("iss") != x["issuer"]:
            raise OAuthError("the reply came from another sign-in server; nothing was connected")
        code = query.get("code")
        if not code:
            raise OAuthError("Bluesky sent no sign-in code; start again")
        reply = self._as_post(x["token_endpoint"], {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": pending.redirect_uri, "client_id": x["client_id"],
            "code_verifier": pending.verifier}, x["dpop_key"], "exchange the sign-in code")
        entry = {"mode": "oauth", "dpop_key": x["dpop_key"], "did": x["did"],
                 "handle": x["handle"], "pds": x["pds"], "issuer": x["issuer"],
                 "token_endpoint": x["token_endpoint"],
                 "revocation_endpoint": x.get("revocation_endpoint"),
                 "client_id": x["client_id"]}
        try:
            tokens = self._tokens(reply, x["did"])
        except OAuthError:
            # A token for another account is not kept, and not left live either.
            if reply.get("access_token"):
                self.revoke(self.default_instance, {
                    **entry, "access_token": str(reply["access_token"]),
                    "refresh_token": reply.get("refresh_token")})
            raise
        entry.update(tokens)
        granted = tuple(str(reply.get("scope") or "").split())
        wider = [s for s in granted if s not in SCOPES]
        if wider or "atproto" not in granted:
            self.revoke(self.default_instance, entry)
            raise OAuthError("Bluesky granted something other than the read calls asked for ("
                             + ", ".join(wider or ["no atproto scope"])
                             + "); it was revoked and not kept")
        return Grant(f"@{x['handle']}", granted, entry)

    def _tokens(self, reply: dict, did: str) -> dict:
        if not reply.get("access_token") or str(reply.get("token_type", "")).lower() != "dpop":
            raise OAuthError("Bluesky returned no DPoP-bound token")
        if reply.get("sub") != did:
            raise OAuthError("the token is for another account than the handle given; "
                             "nothing was kept")
        expires_in = reply.get("expires_in")
        return {"access_token": str(reply["access_token"]),
                "refresh_token": str(reply["refresh_token"]) if reply.get("refresh_token")
                else None,
                "expires_at": time.time() + float(expires_in) if expires_in else None}

    # -- an app password ------------------------------------------------------------------

    def paste(self, fields: dict) -> Grant:
        who = self.resolve(clean_handle(str(fields.get("handle") or "")))
        password = need(fields, "app_password", "The app password")
        try:
            response = self.http.post(f"{who['pds']}/xrpc/com.atproto.server.createSession",
                                      json={"identifier": who["did"], "password": password},
                                      errors=False)
        except SourceError as exc:
            raise OAuthError(f"could not sign in at the PDS ({status_of(exc)})") from None
        if response.status_code in (400, 401):
            raise OAuthError("Bluesky refused the handle and app password")
        reply = self._json(response, "sign in with the app password")
        if reply.get("did") != who["did"] or not reply.get("accessJwt") \
                or not reply.get("refreshJwt"):
            raise OAuthError("Bluesky's session is for another account; nothing was kept")
        if _jwt_claims(str(reply["accessJwt"])).get("scope") != APP_PASS_SCOPE:
            self.revoke(self.default_instance, {
                "mode": "password", "pds": who["pds"],
                "refresh_token": str(reply["refreshJwt"])})
            raise OAuthError("that is not an app password without DM access (an account "
                             "password, or an app password allowed to read messages); the "
                             "session was ended and nothing was kept")
        return Grant(f"@{who['handle']}", ("app password",), {
            "mode": "password", "did": who["did"], "handle": who["handle"], "pds": who["pds"],
            "access_token": str(reply["accessJwt"]), "refresh_token": str(reply["refreshJwt"]),
            "expires_at": _jwt_exp(str(reply["accessJwt"]))})

    # -- using it ----------------------------------------------------------------------

    def headers(self, entry: dict, method: str, url: str) -> dict[str, str]:
        if entry.get("mode") == "password":
            return {**PROXY, "Authorization": f"Bearer {entry['access_token']}"}
        host = urlparse(url).hostname or ""
        return {**PROXY, "Authorization": f"DPoP {entry['access_token']}",
                "DPoP": dpop.proof(entry["dpop_key"], method, url, nonce=self._nonces.get(host),
                                   access_token=entry["access_token"])}

    def observe(self, response: httpx.Response) -> bool:
        """Keep the server's newest nonce; retry once when it asked for one."""
        nonce = response.headers.get("dpop-nonce")
        if nonce:
            self._nonces[response.request.url.host] = nonce
        return bool(nonce) and response.status_code == 401 and \
            "use_dpop_nonce" in response.headers.get("www-authenticate", "")

    def refresh(self, instance: str, entry: dict) -> dict:
        if not entry.get("refresh_token"):
            raise OAuthError("the session expired and has no refresh token")
        if entry.get("mode") == "password":
            try:
                response = self.http.post(
                    f"{entry['pds']}/xrpc/com.atproto.server.refreshSession",
                    headers={"Authorization": f"Bearer {entry['refresh_token']}"}, errors=False)
            except SourceError as exc:
                raise OAuthError(f"could not refresh the session ({status_of(exc)})") from None
            reply = self._json(response, "refresh the session")
            if not reply.get("accessJwt") or not reply.get("refreshJwt"):
                raise OAuthError("Bluesky returned no new session")
            return {"access_token": str(reply["accessJwt"]),
                    "refresh_token": str(reply["refreshJwt"]),
                    "expires_at": _jwt_exp(str(reply["accessJwt"]))}
        reply = self._as_post(entry["token_endpoint"], {
            "grant_type": "refresh_token", "refresh_token": entry["refresh_token"],
            "client_id": entry["client_id"]}, entry["dpop_key"], "refresh the token")
        tokens = self._tokens(reply, entry["did"])
        if not tokens["refresh_token"]:
            tokens.pop("refresh_token")
        return tokens

    def identify(self, http: HTTP, instance: str, entry: dict) -> str:
        """One read call the grant allows (a timeline of one post), then the handle."""
        data = http.get_json(f"{entry['pds']}/xrpc/app.bsky.feed.getTimeline",
                             params={"limit": 1})
        if not isinstance(data, dict) or not isinstance(data.get("feed"), list):
            raise OAuthError("Bluesky answered the test call unexpectedly")
        return f"@{entry['handle']}"

    def revoke(self, instance: str, entry: dict) -> bool:
        try:
            if entry.get("mode") == "password":
                response = self.http.post(
                    f"{entry['pds']}/xrpc/com.atproto.server.deleteSession",
                    headers={"Authorization": f"Bearer {entry.get('refresh_token')}"},
                    errors=False)
                return response.status_code == 200
            if not entry.get("revocation_endpoint"):
                return False
            for token in (entry.get("refresh_token"), entry.get("access_token")):
                if token:
                    self._as_post(entry["revocation_endpoint"],
                                  {"token": token, "client_id": entry["client_id"]},
                                  entry["dpop_key"], "revoke the token", parse=False)
            return True
        except (SourceError, OAuthError) as exc:
            log.warning("bluesky revoke failed: %s", exc if isinstance(exc, OAuthError)
                        else status_of(exc))
            return False

    # -- requests ----------------------------------------------------------------------

    def _get(self, url: str, params: dict | None, what: str) -> dict:
        try:
            data = self.http.get_json(url, params=params)
        except SourceError as exc:
            raise OAuthError(f"could not {what} ({status_of(exc)})") from None
        if not isinstance(data, dict):
            raise OAuthError(f"could not {what}: unexpected reply")
        return data

    def _as_post(self, url: str, data: dict, key: str, what: str, *, ok=(200,),
                 parse: bool = True) -> dict:
        """POST to the authorization server with a DPoP proof, once more with the
        server's nonce if it asks for one."""
        host = urlparse(url).hostname or ""
        response = None
        for _ in range(2):
            proof = dpop.proof(key, "POST", url, nonce=self._nonces.get(host))
            try:
                response = self.http.post(url, data=data, headers={"DPoP": proof},
                                          errors=False)
            except SourceError as exc:
                raise OAuthError(f"could not {what} at Bluesky ({status_of(exc)})") from None
            nonce = response.headers.get("dpop-nonce")
            if nonce:
                self._nonces[host] = nonce
            if response.status_code in (400, 401) and nonce and \
                    _error_of(response) == "use_dpop_nonce":
                continue
            break
        if not parse:
            if response.status_code != 200:
                raise OAuthError(f"could not {what} (HTTP {response.status_code})")
            return {}
        return self._json(response, what, ok)

    @staticmethod
    def _json(response: httpx.Response, what: str, ok=(200,)) -> dict:
        if response.status_code not in ok:
            log.warning("bluesky %s: HTTP %s", what, response.status_code)
            raise OAuthError(f"could not {what} at Bluesky (HTTP {response.status_code})")
        try:
            reply = response.json()
        except ValueError:
            raise OAuthError("Bluesky answered with something other than JSON") from None
        if not isinstance(reply, dict):
            raise OAuthError("Bluesky answered unexpectedly")
        return reply


def _error_of(response: httpx.Response) -> str | None:
    try:
        reply = response.json()
    except ValueError:
        return None
    return reply.get("error") if isinstance(reply, dict) else None
