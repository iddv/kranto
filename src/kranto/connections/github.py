"""GitHub: a pasted fine-grained, read-only token; the device flow once a client id is set.

**A pasted token** (what works today). The owner makes a fine-grained personal
access token on github.com with read-only access to public repositories and no
other permissions, and pastes it. the server makes one identity call
(``GET /user``) to label it. A classic token says what it may do in its
``X-OAuth-Scopes`` reply header; one that can do more than read is refused and
not kept. A fine-grained token's permissions cannot be read back from the API,
so the steps on the page say exactly what to choose.

**The device flow** (OAuth app). It needs an OAuth app with device flow
enabled, registered by the owner; its client id goes in
``connections.github_client_id`` and carries no secret. Until it is set the
page says how to register one. The flow: ``POST /login/device/code`` with
``scope=read:user``, the page shows the code, the owner types it at
github.com/login/device, and the page polls ``/login/oauth/access_token`` no
faster than GitHub's ``interval`` (plus five seconds on each ``slow_down``).

The token is only for the 5,000-an-hour allowance: stars and releases are public
data. Neither kind of token can be revoked by the server (GitHub's revoke endpoint
for OAuth tokens needs the app's secret), so Disconnect deletes it here and the
page names where to revoke it on GitHub.

https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
"""

from __future__ import annotations

import logging

from ..sources.base import HTTP, SourceError
from .base import Bearer, Grant, Provider, need, status_of
from .oauth import OAuthError
from .secret import Secret

log = logging.getLogger(__name__)

API = "https://api.github.com"
DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
DEVICE_SCOPES = ("read:user",)
# A classic token with these scopes, or none, reads public data only.
READ_ONLY_CLASSIC = frozenset({"read:user"})
FINE_GRAINED = "public repositories, read-only"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
SLOW_DOWN_SECONDS = 5


class GitHubProvider(Provider):
    key = "github"
    name = "GitHub"
    scopes = DEVICE_SCOPES
    default_instance = "github.com"

    def __init__(self, http: HTTP, conns=None, client_id: str | None = None) -> None:
        super().__init__(http, conns)
        self.client_id = client_id or None

    def api_host(self, instance: str, entry: dict) -> str:
        return "api.github.com"

    def headers(self, entry: dict, method: str, url: str) -> dict[str, str]:
        return {**HEADERS, "Authorization": f"Bearer {entry['access_token']}"}

    # -- a pasted token ----------------------------------------------------------------

    def paste(self, fields: dict) -> Grant:
        token = Secret(need(fields, "token", "The token"))
        login, scopes = self._check(token)
        return Grant(f"@{login}", scopes, {"access_token": token.reveal(), "via": "token"})

    def _check(self, token: Secret) -> tuple[str, tuple[str, ...]]:
        """(login, scopes) for a token GitHub accepts and that can only read."""
        try:
            response = self.http.with_auth(Bearer("api.github.com", token)).get(
                f"{API}/user", headers=HEADERS)
        except SourceError as exc:
            if exc.needs_login:
                raise OAuthError("GitHub refused this token (HTTP 401): check that it was "
                                 "copied whole and has not expired") from None
            raise OAuthError(f"GitHub did not accept the token ({status_of(exc)})") from None
        header = response.headers.get("x-oauth-scopes")
        if header is None:
            scopes = (FINE_GRAINED,)
        else:
            granted = {s.strip() for s in header.split(",") if s.strip()}
            wider = granted - READ_ONLY_CLASSIC
            if wider:
                raise OAuthError("this token can do more than read ("
                                 + ", ".join(sorted(wider)) + "); it was not kept. Make a "
                                 "fine-grained token with read-only access instead")
            scopes = tuple(sorted(granted)) or ("public data, read-only",)
        login = _login(response)
        return login, scopes

    # -- the device flow ----------------------------------------------------------------

    def device_ready(self) -> bool:
        return bool(self.client_id)

    def device_start(self) -> dict:
        """Ask GitHub for a device and user code: what the page shows, and what is kept."""
        if not self.client_id:
            raise OAuthError("GitHub's device flow needs an OAuth app: set "
                             "connections.github_client_id in kranto.yaml")
        reply = self._post(DEVICE_CODE_URL, {"client_id": self.client_id,
                                             "scope": " ".join(DEVICE_SCOPES)},
                           "start the device sign-in")
        if not reply.get("device_code") or not reply.get("user_code"):
            raise OAuthError("GitHub did not return a device code; is device flow enabled "
                             "for the OAuth app?")
        return {"device_code": str(reply["device_code"]), "user_code": str(reply["user_code"]),
                "verification_uri": str(reply.get("verification_uri")
                                        or "https://github.com/login/device"),
                "interval": max(int(reply.get("interval") or 5), 1),
                "expires_in": int(reply.get("expires_in") or 900)}

    def device_poll(self, device_code: str) -> dict:
        """One poll: ``{"state": pending | slow_down | denied | expired}`` with GitHub's
        new ``interval`` on slow_down, or ``{"state": "granted", "grant": Grant}``."""
        reply = self._post(TOKEN_URL, {"client_id": self.client_id, "device_code": device_code,
                                       "grant_type": DEVICE_GRANT}, "check the device sign-in")
        error = reply.get("error")
        if error == "authorization_pending":
            return {"state": "pending"}
        if error == "slow_down":
            return {"state": "slow_down", "interval": reply.get("interval")}
        if error == "expired_token":
            return {"state": "expired"}
        if error == "access_denied":
            return {"state": "denied"}
        if error or not reply.get("access_token"):
            log.warning("github device poll: %s", str(error)[:60])
            raise OAuthError("GitHub refused the device sign-in; start again")
        token = Secret(str(reply["access_token"]))
        granted = tuple(str(reply.get("scope") or "").replace(",", " ").split())
        wider = set(granted) - set(DEVICE_SCOPES)
        if wider:
            raise OAuthError("GitHub granted more than read:user ("
                             + ", ".join(sorted(wider)) + "); it was not kept. Revoke it under "
                             "Settings, Applications, Authorized OAuth Apps")
        login, _ = self._check(token)
        return {"state": "granted", "grant": Grant(
            f"@{login}", granted or DEVICE_SCOPES,
            {"access_token": token.reveal(), "via": "device"})}

    def _post(self, url: str, data: dict, what: str) -> dict:
        try:
            response = self.http.post(url, data=data, headers={"Accept": "application/json"},
                                      errors=False)
        except SourceError as exc:
            raise OAuthError(f"could not {what} at GitHub ({status_of(exc)})") from None
        if response.status_code != 200:
            log.warning("github %s: HTTP %s", url.rsplit("/", 1)[-1], response.status_code)
            raise OAuthError(f"could not {what} at GitHub (HTTP {response.status_code})")
        try:
            reply = response.json()
        except ValueError:
            raise OAuthError("GitHub answered with something other than JSON") from None
        if not isinstance(reply, dict):
            raise OAuthError("GitHub answered unexpectedly")
        return reply

    # -- using it ----------------------------------------------------------------------

    def identify(self, http: HTTP, instance: str, entry: dict) -> str:
        return "@" + _login(http.get(f"{API}/user", headers=HEADERS))


def _login(response) -> str:
    try:
        data = response.json()
    except ValueError:
        raise OAuthError("GitHub answered /user with something other than JSON") from None
    login = data.get("login") if isinstance(data, dict) else None
    if not isinstance(login, str) or not login:
        raise OAuthError("GitHub did not say which account this is")
    return login
