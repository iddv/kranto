"""YouTube: the owner's own Google Cloud project, authorization code with PKCE.

A project bundled with the server would put every person running it under one
100-user cap and one set of Google policy obligations, so each owner makes
their own (the steps are on the connection page): a project with the YouTube
Data API v3 enabled, an OAuth consent screen published for personal use, and
a "Desktop app" OAuth client. The client id and secret are pasted on the
Connections page and kept in the vault like a token (Google calls a desktop
client's secret "not confidential", but it is still never shown or logged).

The sign-in is an ordinary loopback flow: the redirect is
``http://<localhost or 127.0.0.1>:<port>/connections/youtube/callback``, which
a Desktop client accepts on any port without registering it; scope
``youtube.readonly`` only; ``access_type=offline`` for a refresh token. A grant
with any other scope is revoked and refused. Access tokens last an hour and are
refreshed before a fetch; Disconnect revokes at ``oauth2.googleapis.com/revoke``.
YouTube API data is kept at most 30 days (YouTube's developer policies), which
the retention settings enforce for the ``youtube`` kind.

https://developers.google.com/identity/protocols/oauth2/native-app
"""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlencode

from ..sources.base import HTTP, SourceError
from .base import Bearer, Grant, Provider, reply_json, status_of
from .oauth import OAuthError, Pending
from .secret import Secret

log = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
SCOPES = (SCOPE,)
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # pragma: allowlist secret
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
CLIENT_KEY = "client:youtube"
_CLIENT_ID = re.compile(r"[0-9]{6,30}-[a-z0-9]{8,64}\.apps\.googleusercontent\.com")


class YouTubeProvider(Provider):
    key = "youtube"
    name = "YouTube"
    scopes = SCOPES
    default_instance = "youtube.com"
    browser = True

    def api_host(self, instance: str, entry: dict) -> str:
        return "www.googleapis.com"

    # -- the owner's client --------------------------------------------------------------

    def client(self) -> dict | None:
        return self.vault.get(CLIENT_KEY)

    def set_client(self, fields: dict) -> None:
        client_id = str(fields.get("client_id") or "").strip()
        secret = str(fields.get("client_secret") or "").strip()
        if not _CLIENT_ID.fullmatch(client_id):
            raise OAuthError("that is not a Google OAuth client id: it ends in "
                             ".apps.googleusercontent.com")
        if not secret or len(secret) > 200 or any(c.isspace() for c in secret):
            raise OAuthError("paste the client secret from the same Desktop app client")
        self.vault.put(CLIENT_KEY, {"client_id": client_id, "client_secret": secret})

    def clear_client(self) -> None:
        self.vault.delete(CLIENT_KEY)

    def available(self) -> str | None:
        return None if self.client() else ("paste your Google Cloud project's client id and "
                                           "secret first (steps on this page)")

    # -- the flow ----------------------------------------------------------------------

    def authorize(self, instance: str, value: str, redirect_uri: str, state: str,
                  challenge: str) -> tuple[str, dict]:
        client = self.client()
        if not client:
            raise OAuthError(self.available())
        return AUTHORIZE_URL + "?" + urlencode({
            "client_id": client["client_id"], "redirect_uri": redirect_uri,
            "response_type": "code", "scope": SCOPE, "access_type": "offline",
            "prompt": "consent", "state": state, "code_challenge": challenge,
            "code_challenge_method": "S256"}), {}

    def complete(self, pending: Pending, query: dict) -> Grant:
        client = self.client()
        if not client:
            raise OAuthError("the client id and secret were removed; paste them again")
        code = query.get("code")
        if not code:
            raise OAuthError("Google sent no sign-in code; start again")
        reply = self._post(TOKEN_URL, {
            "code": code, "client_id": client["client_id"],
            "client_secret": client["client_secret"], "redirect_uri": pending.redirect_uri,
            "grant_type": "authorization_code", "code_verifier": pending.verifier},
            "exchange the sign-in code")
        if not reply.get("access_token"):
            raise OAuthError("Google returned no access token")
        entry = {"access_token": str(reply["access_token"]),
                 "refresh_token": str(reply["refresh_token"]) if reply.get("refresh_token")
                 else None,
                 "expires_at": _expiry(reply), "client_id": client["client_id"],
                 "client_secret": client["client_secret"]}
        granted = tuple(str(reply.get("scope") or SCOPE).split())
        wider = set(granted) - set(SCOPES)
        if wider:
            self.revoke(self.default_instance, entry)
            raise OAuthError("Google granted more than read-only YouTube access ("
                             + ", ".join(sorted(wider)) + "); it was revoked and not kept")
        if not entry["refresh_token"]:
            self.revoke(self.default_instance, entry)
            raise OAuthError("Google returned no refresh token; remove the server under your "
                             "Google account's third-party access and connect again")
        try:
            account = self.identify(self.http.with_auth(
                Bearer("www.googleapis.com", Secret(entry["access_token"]))), "", entry)
        except (OAuthError, SourceError):
            # Not kept, so not left live at Google either.
            self.revoke(self.default_instance, entry)
            raise
        return Grant(account, granted, entry)

    # -- using it ----------------------------------------------------------------------

    def refresh(self, instance: str, entry: dict) -> dict:
        if not entry.get("refresh_token"):
            raise OAuthError("the token expired and has no refresh token")
        reply = self._post(TOKEN_URL, {
            "client_id": entry["client_id"], "client_secret": entry["client_secret"],
            "refresh_token": entry["refresh_token"], "grant_type": "refresh_token"},
            "refresh the token")
        if not reply.get("access_token"):
            raise OAuthError("Google returned no access token")
        changes = {"access_token": str(reply["access_token"]), "expires_at": _expiry(reply)}
        if reply.get("refresh_token"):
            changes["refresh_token"] = str(reply["refresh_token"])
        return changes

    def identify(self, http: HTTP, instance: str, entry: dict) -> str:
        """The account's channel name (one unit of quota), or a plain label."""
        try:
            data = http.get_json(f"{API}/channels", params={"part": "snippet", "mine": "true"})
        except SourceError as exc:
            if exc.needs_login:
                raise
            raise OAuthError(f"YouTube did not accept the token ({status_of(exc)})") from None
        items = data.get("items") if isinstance(data, dict) else None
        title = items[0].get("snippet", {}).get("title") if items and isinstance(items[0], dict) \
            else None
        return str(title)[:100] if title else "your Google account (no channel)"

    def revoke(self, instance: str, entry: dict) -> bool:
        token = entry.get("refresh_token") or entry.get("access_token")
        if not token:
            return False
        try:
            response = self.http.post(REVOKE_URL, data={"token": token}, errors=False)
        except SourceError as exc:
            log.warning("google revoke failed: %s", status_of(exc))
            return False
        return response.status_code == 200

    def _post(self, url: str, data: dict, what: str) -> dict:
        try:
            response = self.http.post(url, data=data, errors=False)
        except SourceError as exc:
            raise OAuthError(f"could not {what} at Google ({status_of(exc)})") from None
        return reply_json(response, "Google", what)


def _expiry(reply: dict) -> float | None:
    expires_in = reply.get("expires_in")
    try:
        return time.time() + float(expires_in) if expires_in else None
    except (TypeError, ValueError):
        return None
