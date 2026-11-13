"""Bluesky (posting): the one account Kranto posts as, when the person switches Bluesky to
"Post directly" in Settings › Posting.

Connected with the person's handle and an **app password** (Bluesky's Settings, Privacy and
security, App passwords; direct messages left off). One call,
``com.atproto.server.createSession``, checks it and names the account ``@handle``. The app
password stays in the vault; a session (``accessJwt``, about two hours) is made from it when a
post is sent, and made again when it has run out. Its requests carry the session only to the
person's own server (``bsky.social`` unless they type another).

Separate from the read-only Bluesky connection, which keeps its narrow sign-in and never posts.
Used only by the ``bluesky`` broker adapter, when the person presses Post to Bluesky in the
confirm dialog; nothing else holds it.
"""

from __future__ import annotations

import re
import time

from ..sources.base import SourceError
from .base import Grant, Provider, need, reply_json
from .oauth import OAuthError
from .secret import Secret

SCOPES = ("app.bsky.feed.post",)
DEFAULT_SERVER = "bsky.social"
SESSION_S = 100 * 60          # an accessJwt lasts about two hours; renewed before that
HANDLE = re.compile(r"@?([a-z0-9][a-z0-9.-]{1,252}\.[a-z]{2,63})", re.I)
SERVER = re.compile(r"(?:https://)?([a-z0-9][a-z0-9.-]{1,252}\.[a-z]{2,63})/?", re.I)


def server_of(fields: dict) -> str:
    raw = str(fields.get("server") or "").strip() or DEFAULT_SERVER
    m = SERVER.fullmatch(raw)
    if m is None:
        raise OAuthError("The server is a host name like bsky.social")
    return m.group(1).lower()


class BlueskyPostProvider(Provider):
    key = "bluesky_post"
    name = "Bluesky (posting)"
    scopes = SCOPES
    single = False                # recorded under the person's server
    writes = True
    exclusive = True

    def paste_instance(self, fields: dict) -> str:
        return server_of(fields)

    def _session(self, server: str, handle: str, password: str) -> dict:
        try:
            r = self.http.post(f"https://{server}/xrpc/com.atproto.server.createSession",
                               json={"identifier": handle, "password": password},
                               deadline=30.0, errors=False)
        except SourceError as exc:
            raise OAuthError(f"{server} did not answer ({type(exc).__name__})") from None
        if r.status_code == 401:
            raise OAuthError(f"{server} refused this handle and app password: make a new app "
                             "password and paste it again")
        return reply_json(r, server, "sign in")

    def paste(self, fields: dict) -> Grant:
        server = server_of(fields)
        m = HANDLE.fullmatch(need(fields, "handle", "Your handle"))
        if m is None:
            raise OAuthError("Your handle looks like name.bsky.social")
        handle = m.group(1).lower()
        password = Secret(need(fields, "app_password", "The app password"))
        got = self._session(server, handle, password.reveal())
        token = got.get("accessJwt")
        if not isinstance(token, str) or not token:
            raise OAuthError(f"{server} answered without a session")
        label = str(got.get("handle") or handle)
        return Grant(f"@{label}", SCOPES, {
            "access_token": token, "expires_at": time.time() + SESSION_S,
            "handle": label, "did": str(got.get("did") or ""),
            "app_password": password.reveal()})

    def refresh(self, instance: str, entry: dict) -> dict:
        """A new session from the app password kept in the vault."""
        handle, password = entry.get("handle"), entry.get("app_password")
        if not handle or not password:
            raise OAuthError("the app password is missing: connect Bluesky (posting) again")
        got = self._session(instance, str(handle), str(password))
        token = got.get("accessJwt")
        if not isinstance(token, str) or not token:
            raise OAuthError(f"{instance} answered without a session")
        return {**entry, "access_token": token, "expires_at": time.time() + SESSION_S}

    def identify(self, http, instance: str, entry: dict) -> str:
        return f"@{entry.get('handle') or ''}"


INFO = {
    "key": "bluesky_post", "name": "Bluesky (posting)", "state": "available", "flow": "paste",
    "writes": True,
    "blurb": "The account Kranto posts as on Bluesky, when you switch Bluesky to Post directly "
             "in Settings › Posting. Kranto posts only a draft you approved in the confirm "
             "dialog. Separate from the read-only Bluesky connection.",
    "scopes": list(SCOPES),
    "reads": "Which account it is.",
    "never": "Never posts without your yes on that one draft. Never follows, likes, reposts, "
             "deletes or reads your messages. An app password can do more than post: Kranto "
             "only ever posts with it.",
    "revoke_at": "Bluesky: Settings, Privacy and security, App passwords: delete the one named "
                 "Kranto.",
    "expiry": "no expiry (until you delete the app password)",
    "steps": ["In the Bluesky app open Settings, then Privacy and security, then App passwords, "
              "and add one named Kranto. Leave direct messages off.",
              "Paste your handle (for example name.bsky.social) and that app password below, "
              "and click Save and test. Kranto names the connection @you.",
              "Your server: leave it empty if your account is on bsky.social."],
    "fields": [{"key": "handle", "label": "Your handle", "placeholder": "name.bsky.social"},
               {"key": "app_password", "label": "App password", "secret": True},
               {"key": "server", "label": "Your server (optional)",
                "placeholder": DEFAULT_SERVER}],
    "sources": []}
