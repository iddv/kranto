"""Reddit with your own app (the owner's D-R1): the credentials of an app you
registered with Reddit in your own name, pasted here, never shared and never Kranto's.

Reddit closes its public Data API (its r/redditdev post of 2026-09-30): new access requests end
on **2026-10-31**, the feeds on **2026-11-13**, unregistered apps lose access from
**2027-01-12** and public access ends in **March 2027**. With an app Reddit approved, Kranto
reads your subreddits through Reddit's OAuth API as you: the app's client id and secret and a
refresh token (``duration=permanent``), exchanged for an hour's access token at
``www.reddit.com/api/v1/access_token`` with the app's own credentials (HTTP Basic). Every
request carries a user agent that names the app, its version and you, unmasked, as Reddit's
Data API Terms ask (2.8): ``kranto/<version> (by u/<you>; one person's reading tool)``.

What Kranto does with it, by construction: reads posts and their top comments into your own
library under your retention; republishes nothing, trains nothing; drops what Reddit removed.
Whether a person's own investing tool is "commercial" use is Reddit's to say (its terms do not
define it); the setup page links Reddit's form and says so.
"""

from __future__ import annotations

import base64
import re
import time

import httpx

from .. import __version__
from ..sources.base import HTTP, SourceError
from .base import Grant, Provider, need, reply_json, status_of
from .oauth import OAuthError
from .secret import Secret

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"  # pragma: allowlist secret
API_HOST = "oauth.reddit.com"
SCOPES = ("read", "identity")
_USER = re.compile(r"^[A-Za-z0-9_-]{3,20}$")


def user_agent(account: str | None) -> str:
    """The unmasked user agent Reddit's terms ask for."""
    who = account.removeprefix("u/") if account else "unknown"
    return f"kranto/{__version__} (by u/{who}; one person's reading tool)"


class RedditProvider(Provider):
    key = "reddit"
    name = "Reddit"
    scopes = SCOPES
    default_instance = "reddit.com"

    def api_host(self, instance: str, entry: dict) -> str:
        return API_HOST

    def headers(self, entry: dict, method: str, url: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {entry['access_token']}",
                "User-Agent": user_agent(entry.get("account"))}

    def _token(self, client_id: str, secret: str, refresh_token: str) -> dict:
        basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
        try:
            response = self.http.post(TOKEN_URL, data={"grant_type": "refresh_token",
                                                       "refresh_token": refresh_token},
                                      headers={"Authorization": f"Basic {basic}",
                                               "User-Agent": user_agent(None)}, errors=False)
        except SourceError as exc:
            raise OAuthError(f"could not reach Reddit ({status_of(exc)})") from None
        reply = reply_json(response, "Reddit", "renew the token")
        if not reply.get("access_token"):
            raise OAuthError("Reddit gave no token: check the app's client id, secret and "
                             "refresh token")
        return reply

    def paste(self, fields: dict) -> Grant:
        client_id = need(fields, "client_id", "The app's client id")
        secret = Secret(need(fields, "client_secret", "The app's secret"))
        refresh = Secret(need(fields, "refresh_token", "The refresh token"))
        reply = self._token(client_id, secret.reveal(), refresh.reveal())
        entry = {"access_token": str(reply["access_token"]), "client_id": client_id,
                 "client_secret": secret.reveal(), "refresh_token": refresh.reveal(),
                 "expires_at": time.time() + float(reply.get("expires_in") or 3600)}
        http = self.http.with_auth(_Bearer(API_HOST, entry))
        account = self.identify(http, self.default_instance, entry)
        return Grant(account, SCOPES, {**entry, "account": account})

    def refresh(self, instance: str, entry: dict) -> dict:
        if not entry.get("refresh_token") or not entry.get("client_id"):
            raise OAuthError("the token expired and the app's refresh token is missing")
        reply = self._token(entry["client_id"], entry.get("client_secret") or "",
                            entry["refresh_token"])
        return {"access_token": str(reply["access_token"]),
                "expires_at": time.time() + float(reply.get("expires_in") or 3600)}

    def identify(self, http: HTTP, instance: str, entry: dict) -> str:
        try:
            data = http.get_json(f"https://{API_HOST}/api/v1/me")
        except SourceError as exc:
            raise OAuthError(f"Reddit did not accept the token ({status_of(exc)})") from None
        name = str((data or {}).get("name") or "") if isinstance(data, dict) else ""
        if not _USER.fullmatch(name):
            raise OAuthError("Reddit did not say which account this is")
        return "u/" + name


class _Bearer:
    def __init__(self, host: str, entry: dict) -> None:
        self.host, self._entry = host, entry

    def headers(self, method: str, url: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._entry['access_token']}",
                "User-Agent": user_agent(self._entry.get("account"))}

    def params(self) -> dict[str, str]:
        return {}

    def observe(self, response: httpx.Response) -> bool:
        return False

    def refused(self) -> None:
        return None
