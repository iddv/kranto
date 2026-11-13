"""What every connection provider has in common.

A provider knows how to sign in (a browser flow with state and PKCE, a device
code, or a pasted token or key), how to add its credentials to a request, how
to refresh and revoke them, and which one call says whose account it is. The
``Connections`` registry (``__init__.py``) does the rest: the vault, the
library rows, Needs login, Test and Disconnect.

A provider returns a ``Grant`` when an account is connected: the account's
label and read-only scopes for the library, and the secrets for the vault.
Secrets are plain strings only inside ``Grant.secrets`` on their way to the
vault, and inside a request's headers or query when it is sent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from ..sources.base import HTTP, SourceError
from .oauth import OAuthError, Pending
from .secret import Secret

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Grant:
    """A connected account: its label and scopes (library), its secrets (vault)."""

    account: str
    scopes: tuple[str, ...]
    secrets: dict = field(repr=False)
    note: str = ""                    # what Save and test found besides the account (no secret)


class Bearer:
    """``HTTP.with_auth`` for one call made during a flow, before a connection exists."""

    def __init__(self, host: str, token: Secret, scheme: str = "Bearer") -> None:
        self.host, self._token, self._scheme = host, token, scheme

    def headers(self, method: str, url: str) -> dict[str, str]:
        return {"Authorization": f"{self._scheme} {self._token.reveal()}"}

    def refused(self) -> None:
        return None


class Provider:
    """Defaults for a provider; each one overrides what it does differently."""

    key = ""
    name = ""
    scopes: tuple[str, ...] = ()
    # One account per provider (GitHub, Bluesky, YouTube, ...), recorded under
    # ``default_instance``; Mastodon is one account per instance instead.
    single = True
    default_instance = ""
    # Has a browser sign-in (``/connections/<key>/start`` and ``/callback``).
    browser = False
    # A loopback host name the provider's redirect must use (Bluesky: 127.0.0.1).
    redirect_host: str | None = None
    # A credential that can send or post (a cub's broker: a newsletter platform, Mastodon posting),
    # never used by a source; its scopes are not called read-only anywhere.
    writes = False
    # One live connection per Kranto whatever the instance (the posting account, D7): a
    # new one replaces any other of the provider's.
    exclusive = False

    def __init__(self, http: HTTP, conns=None) -> None:
        self.http = http
        self.conns = conns

    @property
    def vault(self):
        return self.conns.vault

    # -- which account ------------------------------------------------------------------

    def instance(self, value: str | None) -> str:
        return self.default_instance

    def api_host(self, instance: str, entry: dict) -> str:
        """The host a connected account's requests carry its credentials to."""
        return instance

    # -- signing in -----------------------------------------------------------------------

    def available(self) -> str | None:
        """Why this provider cannot be connected right now, or None."""
        return None

    def authorize(self, instance: str, value: str, redirect_uri: str, state: str,
                  challenge: str) -> tuple[str, dict]:
        """The provider's authorize URL, and what the callback will need (kept in the
        vault with the state's PKCE verifier)."""
        raise OAuthError(f"{self.name} has no browser sign-in")

    def complete(self, pending: Pending, query: dict) -> Grant:
        raise OAuthError(f"{self.name} has no browser sign-in")

    def paste(self, fields: dict) -> Grant:
        raise OAuthError(f"{self.name} is not connected with a pasted token")

    def paste_instance(self, fields: dict) -> str:
        """The instance a pasted credential is recorded under (a Mastodon token's server)."""
        return self.default_instance

    # -- using a connection ------------------------------------------------------------------

    def headers(self, entry: dict, method: str, url: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {entry['access_token']}"}

    def params(self, entry: dict) -> dict[str, str]:
        return {}

    def observe(self, response: httpx.Response) -> bool:
        return False

    def refresh(self, instance: str, entry: dict) -> dict:
        """New values for the vault entry; raises ``OAuthError`` when it cannot."""
        raise OAuthError(f"{self.name} tokens cannot be refreshed; connect again")

    def identify(self, http: HTTP, instance: str, entry: dict) -> str:
        """The account's label from one identity call made with ``http`` (authed)."""
        raise OAuthError(f"{self.name} has no identity call")

    def revoke(self, instance: str, entry: dict) -> bool:
        """Revoke at the provider. False when it has no revoke endpoint or did not
        confirm; the token is deleted here either way."""
        return False


# -- helpers -----------------------------------------------------------------------------


def status_of(exc: SourceError) -> str:
    """A short, secret-free description of a failed request: never its full text."""
    text = str(exc)
    at = text.rfind("HTTP ")
    return text[at:at + 40] if at >= 0 else "no reply"


def reply_json(response: httpx.Response, where: str, what: str) -> dict:
    """The JSON object of a 200 reply, or ``OAuthError`` naming only the status.

    The provider's own error text is not echoed (it may quote what was sent)."""
    if response.status_code != 200:
        log.warning("%s: HTTP %s", where, response.status_code)
        raise OAuthError(f"could not {what} ({where}, HTTP {response.status_code})")
    try:
        reply = response.json()
    except ValueError:
        raise OAuthError(f"{where} answered with something other than JSON") from None
    if not isinstance(reply, dict):
        raise OAuthError(f"{where} answered unexpectedly")
    return reply


def need(fields: dict, key: str, what: str) -> str:
    value = str(fields.get(key) or "").strip()
    if not value:
        raise OAuthError(f"{what} is required")
    if len(value) > 4000 or any(c.isspace() for c in value):
        raise OAuthError(f"{what} does not look right: paste it again, without spaces")
    return value
