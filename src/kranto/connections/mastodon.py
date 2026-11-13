"""Mastodon: authorization code with PKCE, an app registered per instance.

Nothing has to be registered by a person. On the first Connect for an instance,
the server calls ``POST /api/v1/apps`` there with its loopback callback and the
read-only scopes, and keeps the returned client id and secret in the vault like
a token (one app per instance and callback URL). The sign-in is then an ordinary
authorization code flow with PKCE (S256), supported since Mastodon 4.3; the
token is exchanged server-side and labelled with one identity call
(``verify_credentials``). Mastodon access tokens do not expire. Disconnect
revokes the token at ``POST /oauth/revoke``.

https://docs.joinmastodon.org/methods/apps/ · https://docs.joinmastodon.org/spec/oauth/
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlencode

from ..sources.base import HTTP, SourceError
from ..sources.mastodon import clean_instance
from .base import Bearer, Grant, Provider, status_of
from .oauth import OAuthError, Pending
from .secret import Secret

log = logging.getLogger(__name__)

# Fixed in code, never configurable: read-only, and only what the sources use.
SCOPES = ("read:accounts", "read:statuses", "read:lists")
CLIENT_NAME = "kranto"
WEBSITE = "https://github.com/iddv/kranto"


@dataclass(frozen=True)
class Token:
    access_token: Secret
    scopes: tuple[str, ...]
    refresh_token: Secret | None = None
    expires_at: float | None = None


def _app_key(instance: str, redirect_uri: str, provider: str = "mastodon") -> str:
    return f"app:{provider}:{instance}|{redirect_uri}"


class MastodonProvider(Provider):
    key = "mastodon"
    name = "Mastodon"
    scopes = SCOPES
    single = False
    browser = True
    client_name = CLIENT_NAME

    def instance(self, value: str | None) -> str:
        try:
            return clean_instance(value or "")
        except ValueError as exc:
            raise OAuthError(str(exc)) from exc

    # -- the flow ----------------------------------------------------------------------

    def authorize(self, instance: str, value: str, redirect_uri: str, state: str,
                  challenge: str) -> tuple[str, dict]:
        key = _app_key(instance, redirect_uri, self.key)
        app = self.vault.get(key)
        if app is None:
            app = self.register(instance, redirect_uri)
            self.vault.put(key, app)
        return self.authorize_url(instance, app, redirect_uri, state, challenge), {}

    def complete(self, pending: Pending, query: dict) -> Grant:
        code = query.get("code")
        if not code:
            raise OAuthError("the instance sent no sign-in code; start again")
        app = self.vault.get(_app_key(pending.instance, pending.redirect_uri, self.key))
        if not app:
            raise OAuthError("the server's app registration for this instance is gone; start again")
        token = self.exchange(pending.instance, app, code, pending.redirect_uri, pending.verifier)
        account = self.identify(self.http.with_auth(Bearer(pending.instance, token.access_token)),
                                pending.instance, {})
        return Grant(account, token.scopes, {
            "access_token": token.access_token.reveal(),
            "refresh_token": token.refresh_token.reveal() if token.refresh_token else None,
            "expires_at": token.expires_at, "client_id": app["client_id"],
            "client_secret": app["client_secret"]})

    def register(self, instance: str, redirect_uri: str) -> dict:
        """Register the server as an app on ``instance``: its client id and secret."""
        reply = self._post(instance, "/api/v1/apps", {
            "client_name": self.client_name, "redirect_uris": redirect_uri,
            "scopes": " ".join(self.scopes), "website": WEBSITE}, "register the server")
        if not reply.get("client_id") or not reply.get("client_secret"):
            raise OAuthError(f"{instance} did not return an app id and secret")
        return {"client_id": str(reply["client_id"]), "client_secret": str(reply["client_secret"])}

    def authorize_url(self, instance: str, app: dict, redirect_uri: str, state: str,
                      challenge: str) -> str:
        return f"https://{instance}/oauth/authorize?" + urlencode({
            "response_type": "code", "client_id": app["client_id"],
            "redirect_uri": redirect_uri, "scope": " ".join(self.scopes), "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"})

    def exchange(self, instance: str, app: dict, code: str, redirect_uri: str,
                 verifier: str) -> Token:
        reply = self._post(instance, "/oauth/token", {
            "grant_type": "authorization_code", "code": code,
            "client_id": app["client_id"], "client_secret": app["client_secret"],
            "redirect_uri": redirect_uri, "code_verifier": verifier,
            "scope": " ".join(self.scopes)}, "exchange the sign-in code")
        token = self._token(instance, reply)
        extra = set(token.scopes) - set(self.scopes)
        if extra:
            # Never keep a grant wider than asked for: give it back and refuse.
            self.revoke(instance, {**app, "access_token": token.access_token.reveal()})
            asked = "was asked for" if self.writes else "read-only access"
            raise OAuthError(f"{instance} granted more than {asked} "
                             f"({', '.join(sorted(extra))}); it was revoked and not kept")
        return token

    def _token(self, instance: str, reply: dict) -> Token:
        if not reply.get("access_token"):
            raise OAuthError(f"{instance} returned no access token")
        expires_in = reply.get("expires_in")
        return Token(Secret(str(reply["access_token"])),
                     tuple(str(reply.get("scope") or " ".join(self.scopes)).split()),
                     Secret(str(reply["refresh_token"])) if reply.get("refresh_token") else None,
                     time.time() + float(expires_in) if expires_in else None)

    # -- using it ------------------------------------------------------------------------

    def refresh(self, instance: str, entry: dict) -> dict:
        """A new access token for a refresh token. Mastodon's tokens do not expire, so
        this runs only for a token issued with an expiry and a refresh token."""
        if not entry.get("refresh_token"):
            raise OAuthError("the token expired and has no refresh token")
        reply = self._post(instance, "/oauth/token", {
            "grant_type": "refresh_token", "refresh_token": entry["refresh_token"],
            "client_id": entry["client_id"], "client_secret": entry["client_secret"],
            "scope": " ".join(self.scopes)}, "refresh the token")
        token = self._token(instance, reply)
        changes = {"access_token": token.access_token.reveal(), "expires_at": token.expires_at}
        if token.refresh_token:
            changes["refresh_token"] = token.refresh_token.reveal()
        return changes

    def identify(self, http: HTTP, instance: str, entry: dict) -> str:
        """The account's label, ``@name@instance``: one identity call."""
        try:
            data = http.get_json(f"https://{instance}/api/v1/accounts/verify_credentials")
        except SourceError as exc:
            if exc.needs_login:
                raise
            raise OAuthError(f"{instance} did not accept the token ({status_of(exc)})") \
                from None
        acct = data.get("acct") if isinstance(data, dict) else None
        if not isinstance(acct, str) or not acct:
            raise OAuthError(f"{instance} did not say which account this is")
        return f"@{acct.split('@')[0]}@{instance}"

    def revoke(self, instance: str, entry: dict) -> bool:
        """Revoke the token at the instance. False if the instance did not confirm."""
        if not entry.get("access_token") or not entry.get("client_id"):
            return False
        try:
            response = self.http.post(f"https://{instance}/oauth/revoke", data={
                "client_id": entry["client_id"], "client_secret": entry["client_secret"],
                "token": entry["access_token"]}, errors=False)
        except SourceError as exc:
            log.warning("mastodon revoke at %s failed: %s", instance, status_of(exc))
            return False
        return response.status_code == 200

    def _post(self, instance: str, path: str, data: dict, what: str) -> dict:
        try:
            response = self.http.post(f"https://{instance}{path}", data=data, errors=False)
        except SourceError as exc:
            raise OAuthError(f"could not {what} at {instance} ({status_of(exc)})") from None
        if response.status_code != 200:
            # The provider's own error text is not echoed (it may quote what was sent);
            # the status code is enough to say where it failed.
            log.warning("mastodon %s at %s: HTTP %s", path, instance, response.status_code)
            raise OAuthError(f"could not {what} at {instance} (HTTP {response.status_code})")
        try:
            reply = response.json()
        except ValueError:
            raise OAuthError(f"{instance} answered {path} with something other than JSON") \
                from None
        if not isinstance(reply, dict):
            raise OAuthError(f"{instance} answered {path} unexpectedly")
        return reply
