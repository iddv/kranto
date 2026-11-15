"""Mastodon (posting): the one account a cub's posts go out as.

The same PKCE sign-in as the read-only ``mastodon`` provider, with its own app registration on
the instance (client name "Kranto (posting)") and its own scopes, ``read:accounts
write:statuses``: enough to say whose account it is and to publish a status, nothing else (no
follows, no deletes, no messages read). The read-only provider keeps its scopes and never posts.

Without a browser sign-in (an instance without PKCE), the owner makes an access token on the
instance's Development page with exactly these two scopes and pastes it with the instance's
name; one ``verify_credentials`` call labels it ``@user@instance``.

One posting account per Kranto: connecting another replaces the first, whatever its instance.
It is used only by the ``mastodon`` broker adapter, when the owner presses a cub's ticket; the
cub never sees the token.
"""

from __future__ import annotations

from ..sources.base import SourceError
from .base import Bearer, Grant, need, status_of
from .mastodon import MastodonProvider
from .oauth import OAuthError
from .secret import Secret

SCOPES = ("read:accounts", "write:statuses")
CLIENT_NAME = "Kranto (posting)"


class MastodonPostProvider(MastodonProvider):
    key = "mastodon_post"
    name = "Mastodon (posting)"
    scopes = SCOPES
    client_name = CLIENT_NAME
    writes = True
    exclusive = True

    def paste_instance(self, fields: dict) -> str:
        return self.instance(need(fields, "instance", "The instance"))

    def paste(self, fields: dict) -> Grant:
        instance = self.paste_instance(fields)
        token = Secret(need(fields, "token", "The access token"))
        http = self.http.with_auth(Bearer(instance, token))
        try:
            account = self.identify(http, instance, {})
        except SourceError as exc:
            if exc.needs_login:
                raise OAuthError(f"{instance} refused this token (HTTP 401): copy the access "
                                 "token again from Preferences, Development") from None
            raise OAuthError(f"{instance} did not accept the token ({status_of(exc)})") \
                from None
        return Grant(account, SCOPES, {"access_token": token.reveal()})
