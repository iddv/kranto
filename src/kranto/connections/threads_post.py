"""Threads (posting): the person's own Meta app, with themselves as its Threads tester, and a
long-lived token made with it, so Kranto can post a draft they approved.

One call, ``GET https://graph.threads.com/v1.0/me?fields=id,username``, checks the token and
names the account ``@username``. A long-lived token lasts 60 days and is refreshed by Kranto
(``GET https://graph.threads.com/refresh_access_token?grant_type=th_refresh_token``) once it is
at least a day old, before it runs out; each refresh restarts the 60 days.

Sources (read 2026-11-13): developers.facebook.com/docs/threads/get-started (testers, the
permissions), …/get-started/long-lived-tokens (the refresh), …/threads-profiles (``me``).
"""

from __future__ import annotations

import time

from ..sources.base import SourceError
from .base import Bearer, Grant, Provider, need, reply_json, status_of
from .oauth import OAuthError
from .secret import Secret

SCOPES = ("threads_basic", "threads_content_publish", "threads_manage_insights")
HOST = "graph.threads.com"
LIFETIME_S = 60 * 86400
REFRESH_AFTER_S = 86400          # Meta: a token at least 24 hours old, not expired


class _Token(Bearer):
    """A pasted token for the one check before it is kept (the HTTP layer's ``Auth``)."""

    def params(self) -> dict[str, str]:
        return {}

    def observe(self, response) -> bool:
        return False


class ThreadsPostProvider(Provider):
    key = "threads_post"
    name = "Threads (posting)"
    scopes = SCOPES
    default_instance = HOST
    writes = True
    exclusive = True

    def headers(self, entry: dict, method: str, url: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {entry['access_token']}"}

    def paste(self, fields: dict) -> Grant:
        token = Secret(need(fields, "token", "The access token"))
        http = self.http.with_auth(_Token(HOST, token))
        try:
            r = http.get(f"https://{HOST}/v1.0/me", params={"fields": "id,username"},
                         deadline=30.0, errors=False)
        except SourceError as exc:
            if exc.needs_login:
                raise OAuthError("Threads refused this token: generate a new one under User "
                                 "token generator in your app, and paste it again") from None
            raise OAuthError(f"Threads did not answer ({status_of(exc)})") from None
        if r.status_code in (400, 401):
            raise OAuthError("Threads refused this token: generate a new one under User token "
                             "generator in your app, and paste it again")
        info = reply_json(r, "Threads", "read whose token this is")
        user = str(info.get("username") or "").strip()
        if not user or not info.get("id"):
            raise OAuthError("Threads did not say whose token this is")
        now = time.time()
        return Grant(f"@{user}", SCOPES, {"access_token": token.reveal(),
                                          "user_id": str(info["id"]), "made_at": now,
                                          "expires_at": now + LIFETIME_S})

    def refresh(self, instance: str, entry: dict) -> dict:
        """A refreshed long-lived token (60 days again), once the token is a day old."""
        if time.time() - float(entry.get("made_at") or 0) < REFRESH_AFTER_S:
            raise OAuthError("the Threads token is under a day old: it cannot be refreshed yet")
        try:
            r = self.http.get(f"https://{HOST}/refresh_access_token",
                              params={"grant_type": "th_refresh_token",
                                      "access_token": entry["access_token"]},
                              deadline=30.0, errors=False)
        except SourceError as exc:
            raise OAuthError(f"Threads did not answer ({status_of(exc)})") from None
        got = reply_json(r, "Threads", "refresh the token")
        token = got.get("access_token")
        if not isinstance(token, str) or not token:
            raise OAuthError("Threads answered without a token: connect Threads (posting) again")
        expires = got.get("expires_in")
        life = float(expires) if isinstance(expires, int | float) else LIFETIME_S
        now = time.time()
        return {**entry, "access_token": token, "made_at": now, "expires_at": now + life}

    def identify(self, http, instance: str, entry: dict) -> str:
        return "your Threads account"


INFO = {
    "key": "threads_post", "name": "Threads (posting)", "state": "available", "flow": "paste",
    "writes": True,
    "blurb": "Your own Meta app's token, so Kranto can post to Threads a draft you approved in "
             "the confirm dialog. Without it, Threads still opens with the draft written.",
    "scopes": list(SCOPES),
    "reads": "Which account it is, and the numbers of the posts Kranto sent (views, likes, "
             "replies, reposts, quotes), once a day.",
    "never": "Never posts without your yes on that one draft. Never replies, likes, follows or "
             "reads your messages. The app stays in development mode, for you only.",
    "revoke_at": "threads.com: Settings, Account, Website permissions.",
    "expiry": "60 days, refreshed by Kranto while you use it",
    "steps": ["Open developers.facebook.com/apps and choose Create app. Pick the use case "
              "Access the Threads API. Name it Kranto.",
              "In the app open Use cases, then Customize beside Threads, and add "
              "threads_content_publish and threads_manage_insights (threads_basic is "
              "already there). The second lets Kranto read how your posts did.",
              "Open App roles, then Roles, then Add people, and add your own Threads account as "
              "a Threads tester.",
              "In Threads: Settings, Account, Website permissions, Invites: accept the "
              "invitation from your app.",
              "Back in the app's Threads settings, under User token generator, choose Generate "
              "access token beside your account, allow, and copy the token.",
              "Paste it below and choose Save and test. Kranto names the connection @you."],
    "fields": [{"key": "token", "label": "Access token", "secret": True}],
    "sources": []}
