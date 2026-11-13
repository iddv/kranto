"""Providers connected with a pasted credential and no browser flow.

**Product Hunt**: a developer token, made under an application on
producthunt.com's API dashboard. A new application's token has the ``public``
scope, which reads public data only (``private`` and ``write`` need Product
Hunt's approval). One GraphQL query (``viewer``) labels it. It does not expire;
it is revoked by deleting it on the dashboard.

**Stack Exchange**: an app key from stackapps.com. It is not a login and reads
nothing private: it raises the daily allowance from 300 requests per address to
10,000. It travels as the ``key`` query parameter, added at send time like a
token's header and never part of a URL an error names. ``/info`` checks it:
with an accepted key the reply's ``quota_max`` is 10,000.
"""

from __future__ import annotations

import logging

from ..sources.base import HTTP, SourceError
from .base import Grant, Provider, need, status_of
from .oauth import OAuthError
from .secret import Secret

log = logging.getLogger(__name__)


class _Header:
    def __init__(self, host: str, headers: dict) -> None:
        self.host, self._headers = host, headers

    def headers(self, method: str, url: str) -> dict:
        return dict(self._headers)

    def refused(self) -> None:
        return None


class _Param:
    def __init__(self, host: str, params: dict) -> None:
        self.host, self._params = host, params

    def headers(self, method: str, url: str) -> dict:
        return {}

    def params(self) -> dict:
        return dict(self._params)

    def refused(self) -> None:
        return None


# -- Product Hunt ---------------------------------------------------------------------------

PH_API = "https://api.producthunt.com/v2/api/graphql"
PH_SCOPES = ("public",)


class ProductHuntProvider(Provider):
    key = "producthunt"
    name = "Product Hunt"
    scopes = PH_SCOPES
    default_instance = "producthunt.com"

    def api_host(self, instance: str, entry: dict) -> str:
        return "api.producthunt.com"

    def paste(self, fields: dict) -> Grant:
        token = Secret(need(fields, "token", "The developer token"))
        http = self.http.with_auth(_Header("api.producthunt.com",
                                           {"Authorization": f"Bearer {token.reveal()}"}))
        try:
            account = self.identify(http, self.default_instance, {})
        except SourceError as exc:
            if exc.needs_login:
                raise OAuthError("Product Hunt refused this token (HTTP 401): copy the "
                                 "developer token again") from None
            raise OAuthError(f"Product Hunt did not accept the token ({status_of(exc)})") \
                from None
        return Grant(account, PH_SCOPES, {"access_token": token.reveal()})

    def identify(self, http: HTTP, instance: str, entry: dict) -> str:
        response = http.post(PH_API, json={"query": "{ viewer { user { username } } }"},
                             headers={"Accept": "application/json"})
        try:
            data = response.json()
        except ValueError:
            raise OAuthError("Product Hunt answered with something other than JSON") from None
        user = (((data or {}).get("data") or {}).get("viewer") or {}).get("user") \
            if isinstance(data, dict) else None
        if isinstance(user, dict) and user.get("username"):
            return "@" + str(user["username"])[:60]
        if isinstance(data, dict) and data.get("data") is not None:
            return "developer token"
        raise OAuthError("Product Hunt did not accept the token")


# -- Stack Exchange --------------------------------------------------------------------------

SE_API = "https://api.stackexchange.com/2.3"
SE_SCOPES = ("public read",)
KEYED_QUOTA = 10_000


class StackExchangeProvider(Provider):
    key = "stackexchange"
    name = "Stack Exchange"
    scopes = SE_SCOPES
    default_instance = "stackexchange.com"

    def api_host(self, instance: str, entry: dict) -> str:
        return "api.stackexchange.com"

    def headers(self, entry: dict, method: str, url: str) -> dict[str, str]:
        return {}

    def params(self, entry: dict) -> dict[str, str]:
        return {"key": entry["key"]}

    def paste(self, fields: dict) -> Grant:
        key = Secret(need(fields, "key", "The key"))
        http = self.http.with_auth(_Param("api.stackexchange.com", {"key": key.reveal()}))
        try:
            account = self.identify(http, self.default_instance, {})
        except SourceError as exc:
            raise OAuthError(f"Stack Exchange did not accept the key ({status_of(exc)}): "
                             "copy the Key, not the Client Secret") from None
        return Grant(account, SE_SCOPES, {"key": key.reveal()})

    def identify(self, http: HTTP, instance: str, entry: dict) -> str:
        data = http.get_json(f"{SE_API}/info", params={"site": "stackoverflow"})
        quota = data.get("quota_max") if isinstance(data, dict) else None
        if not isinstance(quota, int) or quota < KEYED_QUOTA:
            raise OAuthError("Stack Exchange did not apply the key (the daily allowance is "
                             f"still {quota}); copy the Key, not the Client Secret")
        return f"app key, {quota:,} requests a day"
