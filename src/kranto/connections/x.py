"""X: the person's own developer app (a public "Native App"), authorization code with PKCE.

X sells API reads per resource returned, and the credits belong to the developer account that
owns the app, so an app bundled with Kranto would put every install's reads on one card and lose
the price X gives an app's owner for their own bookmarks and likes. Each person registers their
own app instead (the steps are on the connection page, 5.1): type Native App, which
is a public client with no secret, read-only permissions, and the callback
``http://127.0.0.1:<port>/connections/x/callback`` exactly as the page prints it (X matches the
callback exactly, and asks local apps for 127.0.0.1 rather than localhost). The client id is
pasted on the Connections page and kept in the vault; it is not a secret, but it is the
person's.

The sign-in: ``x.com/i/oauth2/authorize`` with ``code_challenge_method=S256`` and the scopes
below (fixed here, never configurable); the callback exchanges the code at once (X's codes live
30 seconds), ``client_id`` in the body and no secret; one identity call (``/2/users/me``)
labels the account ``@username`` and keeps its numeric id for the timelines that need it. A
grant with any scope beyond these, or without a refresh token, is revoked and refused.

Tokens last two hours. X rotates the refresh token on every refresh and the old one stops
working, so ``afk serve`` and a cron ``afk run`` must not both spend it: this provider says
``rotates_refresh`` and the registry refreshes it under the vault's file lock (read the entry,
ask X, write the new pair, release). Disconnect revokes the refresh token, then the access
token, at ``/2/oauth2/revoke``.

https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code
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

# Read-only, and only what the sources use; offline.access is what makes X return a refresh
# token. Fixed in code, never configurable.
SCOPES = ("tweet.read", "users.read", "list.read", "bookmark.read", "like.read",
          "offline.access")
AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
API_HOST = "api.x.com"
API = f"https://{API_HOST}/2"
TOKEN_URL = f"{API}/oauth2/token"
REVOKE_URL = f"{API}/oauth2/revoke"
CLIENT_KEY = "client:x"
# X shows a Native App's OAuth 2.0 client id as a base64url string of about 34 characters.
_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{16,100}")
_USERNAME = re.compile(r"[A-Za-z0-9_]{1,15}")


class XProvider(Provider):
    key = "x"
    name = "X"
    scopes = SCOPES
    default_instance = "x.com"
    browser = True
    redirect_host = "127.0.0.1"
    # X spends the old refresh token when it issues a new one (Connections._refresh).
    rotates_refresh = True

    def api_host(self, instance: str, entry: dict) -> str:
        return API_HOST

    # -- what each reply cost --------------------------------------------------------------

    def observe(self, response) -> bool:
        """Every reply to a connected X account's request: what it returned goes in the
        ``api_spend`` ledger (``spend``). Never asks for the request to be sent again."""
        if response.status_code != 200 or self.conns is None:
            return False
        try:
            body = response.json()
        except ValueError:
            return False
        if not isinstance(body, dict):
            return False
        from .. import spend

        for kind, count in reads_of(response.request.url.path, body).items():
            try:
                spend.record(self.conns.store, "x", kind, count)
            except Exception:  # noqa: BLE001 - the ledger must never fail a fetch
                log.warning("could not record an X read in api_spend")
        return False

    # -- the person's app ----------------------------------------------------------------

    def client(self) -> dict | None:
        return self.vault.get(CLIENT_KEY)

    def set_client(self, fields: dict) -> None:
        client_id = str(fields.get("client_id") or "").strip()
        if not _CLIENT_ID.fullmatch(client_id):
            raise OAuthError("that is not an X OAuth 2.0 client id: copy the Client ID from your "
                             "app's Keys and tokens page (letters, digits, - and _)")
        self.vault.put(CLIENT_KEY, {"client_id": client_id})

    def clear_client(self) -> None:
        self.vault.delete(CLIENT_KEY)

    def available(self) -> str | None:
        return None if self.client() else ("paste your X app's client id first (steps on this "
                                           "page)")

    # -- the flow ------------------------------------------------------------------------

    def authorize(self, instance: str, value: str, redirect_uri: str, state: str,
                  challenge: str) -> tuple[str, dict]:
        client = self.client()
        if not client:
            raise OAuthError(self.available())
        return AUTHORIZE_URL + "?" + urlencode({
            "response_type": "code", "client_id": client["client_id"],
            "redirect_uri": redirect_uri, "scope": " ".join(SCOPES), "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"}), {}

    def complete(self, pending: Pending, query: dict) -> Grant:
        client = self.client()
        if not client:
            raise OAuthError("the client id was removed; paste it again")
        code = query.get("code")
        if not code:
            raise OAuthError("X sent no sign-in code; start again")
        reply = self._post(TOKEN_URL, {
            "grant_type": "authorization_code", "code": code,
            "client_id": client["client_id"], "redirect_uri": pending.redirect_uri,
            "code_verifier": pending.verifier}, "exchange the sign-in code")
        if not reply.get("access_token"):
            raise OAuthError("X returned no access token")
        entry = {"client_id": client["client_id"], "access_token": str(reply["access_token"]),
                 "refresh_token": str(reply["refresh_token"]) if reply.get("refresh_token")
                 else None, "expires_at": _expiry(reply), "via": "oauth"}
        granted = tuple(str(reply.get("scope") or " ".join(SCOPES)).split())
        wider = set(granted) - set(SCOPES)
        if wider:
            self.revoke(self.default_instance, entry)
            raise OAuthError("X granted more than read-only access (" + ", ".join(sorted(wider))
                             + "); it was revoked and not kept")
        if not entry["refresh_token"]:
            self.revoke(self.default_instance, entry)
            raise OAuthError("X returned no refresh token (offline.access was not granted); "
                             "connect again and allow it")
        try:
            user_id, username = self.me(self.http.with_auth(
                Bearer(API_HOST, Secret(entry["access_token"]))))
        except (OAuthError, SourceError):
            # Not kept, so not left live at X either.
            self.revoke(self.default_instance, entry)
            raise
        if self.conns is not None:
            # made before the connection exists, so outside observe: one user read
            from .. import spend

            spend.record(self.conns.store, "x", "user_read", 1)
        return Grant(f"@{username}", granted, {**entry, "user_id": user_id})

    # -- using it ------------------------------------------------------------------------

    def refresh(self, instance: str, entry: dict) -> dict:
        """A new access token and the new refresh token X rotates in. Called under the vault's
        file lock (``rotates_refresh``): the old refresh token stops working once X answers."""
        if not entry.get("refresh_token") or not entry.get("client_id"):
            raise OAuthError("the token expired and has no refresh token")
        reply = self._post(TOKEN_URL, {
            "grant_type": "refresh_token", "refresh_token": entry["refresh_token"],
            "client_id": entry["client_id"]}, "refresh the token")
        if not reply.get("access_token") or not reply.get("refresh_token"):
            raise OAuthError("X returned no new token pair")
        return {"access_token": str(reply["access_token"]),
                "refresh_token": str(reply["refresh_token"]), "expires_at": _expiry(reply)}

    def me(self, http: HTTP) -> tuple[str, str]:
        """(the account's numeric id, its username) from ``/2/users/me``: one user read."""
        try:
            data = http.get_json(f"{API}/users/me")
        except SourceError as exc:
            if exc.needs_login:
                raise
            raise OAuthError(f"X did not accept the token ({status_of(exc)})") from None
        user = data.get("data") if isinstance(data, dict) else None
        user_id = str(user.get("id") or "") if isinstance(user, dict) else ""
        username = str(user.get("username") or "") if isinstance(user, dict) else ""
        if not user_id.isdigit() or not _USERNAME.fullmatch(username):
            raise OAuthError("X did not say which account this is")
        return user_id, username

    def identify(self, http: HTTP, instance: str, entry: dict) -> str:
        return "@" + self.me(http)[1]

    def revoke(self, instance: str, entry: dict) -> bool:
        """Revoke the refresh token, then the access token. True only when X confirmed both
        that were held."""
        if not entry.get("client_id"):
            return False
        done = []
        for hint in ("refresh_token", "access_token"):
            token = entry.get(hint)
            if not token:
                continue
            try:
                response = self.http.post(REVOKE_URL, data={
                    "token": token, "token_type_hint": hint,
                    "client_id": entry["client_id"]}, errors=False)
            except SourceError as exc:
                log.warning("x revoke failed: %s", status_of(exc))
                done.append(False)
                continue
            done.append(response.status_code == 200)
        return bool(done) and all(done)

    def _post(self, url: str, data: dict, what: str) -> dict:
        try:
            response = self.http.post(url, data=data, errors=False)
        except SourceError as exc:
            raise OAuthError(f"could not {what} at X ({status_of(exc)})") from None
        return reply_json(response, "X", what)


_OWNED = re.compile(r"^/2/users/\d+/(?:bookmarks|liked_tweets)$")


def reads_of(path: str, body: dict) -> dict[str, int]:
    """The resources one X reply returned, by price line (``pricing.X_PRICES``). The person's
    own bookmarks and likes are owned reads (their own app reads them); a post a reply carries
    in ``includes`` (a quoted or reposted original) is a post read; a user is a user read."""
    out: dict[str, int] = {}
    data = body.get("data")
    rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    includes = body.get("includes") if isinstance(body.get("includes"), dict) else {}
    if path == "/2/users/me" or path.startswith("/2/users/by/"):
        line = "user_read"
    elif re.fullmatch(r"/2/lists/\d+", path) or path.endswith("/owned_lists"):
        line = "list_read"
    elif _OWNED.match(path):
        line = "owned_read"
    else:
        line = "post_read"
    if rows:
        out[line] = len(rows)
    posts = includes.get("posts") or includes.get("tweets")
    if isinstance(posts, list) and posts:
        out["post_read"] = out.get("post_read", 0) + len(posts)
    users = includes.get("users")
    if isinstance(users, list) and users:
        out["user_read"] = out.get("user_read", 0) + len(users)
    return out


def _expiry(reply: dict) -> float | None:
    expires_in = reply.get("expires_in")
    try:
        return time.time() + float(expires_in) if expires_in else None
    except (TypeError, ValueError):
        return None
