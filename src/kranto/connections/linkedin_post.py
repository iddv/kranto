"""LinkedIn (posting): the person's own LinkedIn app and a token they made with it, so that
Kranto can post to their profile a draft they approved. LinkedIn has no link that fills in a
post's text, so posting directly is the only way Kranto offers LinkedIn.

The token comes from LinkedIn's developer portal (Docs and tools, OAuth Token Tools, Create
token) with the scopes ``openid``, ``profile`` and ``w_member_social``. One call,
``GET https://api.linkedin.com/v2/userinfo``, checks it and gives the member's id (``sub``: the
post's author is ``urn:li:person:<sub>``) and name. LinkedIn issues a token for 60 days and does
not refresh one for an app like this: Kranto keeps the day it expires and says so a week before
(Needs you), and the person makes a new one.

Sources (read 2026-11-13): Sign In with LinkedIn using OpenID Connect
(learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2),
the authorization code flow ("all access tokens are issued with a 60-day lifespan"), Share on
LinkedIn (``w_member_social``).
"""

from __future__ import annotations

import time

from ..sources.base import SourceError
from .base import Bearer, Grant, Provider, need, reply_json, status_of
from .oauth import OAuthError
from .secret import Secret

SCOPES = ("openid", "profile", "w_member_social")
HOST = "api.linkedin.com"
LIFETIME_S = 60 * 86400


class LinkedInPostProvider(Provider):
    key = "linkedin_post"
    name = "LinkedIn (posting)"
    scopes = SCOPES
    default_instance = HOST
    writes = True
    exclusive = True

    def paste(self, fields: dict) -> Grant:
        token = Secret(need(fields, "token", "The access token"))
        http = self.http.with_auth(Bearer(HOST, token))
        try:
            r = http.get(f"https://{HOST}/v2/userinfo", deadline=30.0, errors=False)
        except SourceError as exc:
            if exc.needs_login:
                raise OAuthError("LinkedIn refused this token (HTTP 401): make a new one with "
                                 "openid, profile and w_member_social, and paste it again") \
                    from None
            raise OAuthError(f"LinkedIn did not answer ({status_of(exc)})") from None
        if r.status_code == 401:
            raise OAuthError("LinkedIn refused this token (HTTP 401): make a new one with "
                             "openid, profile and w_member_social, and paste it again")
        info = reply_json(r, "LinkedIn", "read who the token is for")
        sub = info.get("sub")
        if not isinstance(sub, str) or not sub:
            raise OAuthError("LinkedIn did not say whose token this is: tick openid and profile")
        name = str(info.get("name") or "").strip()[:80] or "your profile"
        now = time.time()
        return Grant(name, SCOPES, {"access_token": token.reveal(), "sub": sub,
                                    "made_at": now, "expires_by": now + LIFETIME_S},
                     note="LinkedIn's tokens last 60 days: Kranto says so a week before.")

    def identify(self, http, instance: str, entry: dict) -> str:
        return "your LinkedIn profile"


INFO = {
    "key": "linkedin_post", "name": "LinkedIn (posting)", "state": "available", "flow": "paste",
    "writes": True,
    "blurb": "Your own LinkedIn app's token, so Kranto can post to your profile a draft you "
             "approved in the confirm dialog. LinkedIn has no link that fills in a post, so this "
             "is the only way Kranto offers LinkedIn.",
    "scopes": list(SCOPES),
    "reads": "Your name and your member id (to name the post's author).",
    "never": "Never posts without your yes on that one draft. Never reads your feed, your "
             "messages or your numbers (LinkedIn gives them to approved partners only).",
    "revoke_at": "linkedin.com, Settings, Data privacy, Permitted services.",
    "expiry": "60 days: Kranto says so a week before, and you make a new token (5 minutes)",
    "steps": ["You need a LinkedIn Page to attach the app to. Any Page you manage will do; "
              "LinkedIn's Create a company page takes a minute and can stay empty.",
              "Open linkedin.com/developers/apps and choose Create app. Name it Kranto, pick "
              "your Page, add any small picture as its logo, tick the box, Create app.",
              "On the app's Products tab, request Share on LinkedIn and Sign In with LinkedIn "
              "using OpenID Connect.",
              "Open Docs and tools, then OAuth Token Tools, then Create token. Pick your app, "
              "tick openid, profile and w_member_social, and choose Request access token. Sign "
              "in and allow.",
              "Paste the access token below and choose Save and test. Kranto names the "
              "connection with your name."],
    "fields": [{"key": "token", "label": "Access token", "secret": True}],
    "sources": []}
