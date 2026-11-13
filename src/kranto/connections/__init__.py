"""Connected accounts: sources that read with the owner's own login.

The library database holds a connection's provider, instance, account label and
read-only scopes (``connections``) and what happened to it
(``connection_events``: connected, tested, needs_login, disconnected). Secrets
(access and refresh tokens, a DPoP key, an app key, the client id and secret an
instance minted or the owner pasted) are in the vault (``vault.py``), keyed
``conn:<id>``, encrypted, never in a table, a log line, an event note, an export
or a page.

A source of a kind that needs a connection (``sources.needs``) gets an ``HTTP``
from ``http_for``: the same client with ``ConnectionAuth``, which adds the
provider's credentials at send time (a header, a DPoP proof, or a query key),
refreshes a token within five minutes of expiry under a lock, and marks the
connection ``needs_login`` when the provider refuses it (HTTP 401) or a refresh
fails. The run continues, and the source's row and the Connections page say
"Needs login".

Providers (``base.Provider``): Mastodon (browser, an app registered per
instance), Bluesky (browser OAuth with DPoP, or an app password), GitHub (a
pasted fine-grained token; the device flow once ``connections.github_client_id``
is set), YouTube (browser, with the owner's own Google Cloud client), Product
Hunt (a pasted developer token), Stack Exchange (a pasted app key) and X (browser,
with the owner's own developer app; 5.1). Reddit and LinkedIn are
listed as not offered, with the reason.

Some providers hold a credential that sends rather than reads (``Provider.writes``), for the
cubs' broker adapters: Mastodon posting (a token with ``write:statuses``; one
per Kranto) and each newsletter platform (``kranto.newsletter``: its module registers its
provider here with ``register``). No source uses them; only the owner's press of a cub's
ticket does, and the cub never sees them.
"""

from __future__ import annotations

import contextlib
import copy
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from ..sources.base import HTTP, SourceError
from ..store import Store, iso, utcnow
from ..stored.misc import ConnectionScopes
from . import oauth
from .base import Grant, Provider
from .bluesky import BlueskyProvider
from .github import GitHubProvider
from .mastodon import MastodonProvider
from .mastodon_post import MastodonPostProvider
from .oauth import OAuthError
from .pasted import ProductHuntProvider, StackExchangeProvider
from .reddit import RedditProvider
from .sanity import INFO as SANITY_INFO
from .sanity import SanityProvider
from .secret import Secret
from .vault import Vault, VaultError, crypto_available
from .x import XProvider
from .youtube import YouTubeProvider

log = logging.getLogger(__name__)

__all__ = ["ConnectionAuth", "Connections", "OAuthError", "PROVIDER_INFO", "Secret", "Vault",
           "VaultError"]

REFRESH_WITHIN_SECONDS = 300
# How often "last used" is written back to the vault for one connection.
TOUCH_EVERY_SECONDS = 600
STATES = ("connected", "needs_login", "disconnected")

# What the Connections page lists, in order (3.1 and 3.2, and the
# owner's decisions of 6 Oct 2026). ``state``: available or not_offered. ``flow``:
# browser (a sign-in), paste (a token or key), both, or client (the owner's own
# OAuth client first, then a sign-in). ``steps`` are what the owner does, in order;
# ``fields`` are what is pasted (``secret`` fields are never echoed back). A client
# provider's page has two parts: ``client_section`` names the first (every step but
# the last two), ``client_ready`` is what it says until the client is saved, and the
# last two steps are the sign-in.
PROVIDER_INFO = [
    {"key": "mastodon", "name": "Mastodon", "state": "available", "flow": "browser",
     "blurb": "Type your instance, click Connect, allow. Kranto registers itself with the "
              "instance; there is nothing to set up first.",
     "scopes": list(MastodonProvider.scopes),
     "reads": "Your home timeline and your lists, as the sources you add from them.",
     "never": "Never posts, boosts, favourites, follows or changes anything.",
     "revoke_at": "Preferences, then Account, then Authorized apps, on your instance.",
     "expiry": "no expiry",
     "steps": ["Type your instance, the server your account is on.",
               "Click Connect. Kranto registers itself with the instance (nothing for you to "
               "set up) and sends you there.",
               "Sign in if asked, and allow read-only access. The instance sends you back "
               "here."],
     "sources": ["Your home timeline", "A list of yours"]},
    {"key": "bluesky", "name": "Bluesky", "state": "available", "flow": "both",
     "redirect_host": "127.0.0.1",
     "blurb": "Sign in with read-only scopes (OAuth with DPoP; nothing to register), or paste an "
              "app password. For your home timeline and search.",
     "scopes": list(BlueskyProvider.scopes),
     "reads": "Your home timeline and post search, as the sources you add from them.",
     "never": "Never posts, likes, reposts, follows or reads your messages. The OAuth grant "
              "lists only these read calls; anything wider is revoked and refused.",
     "revoke_at": "Settings, then Privacy and security, then Connected apps (OAuth) or App "
                  "passwords, in the Bluesky app.",
     "expiry": "refreshed automatically",
     "steps": ["Open Kranto as http://127.0.0.1:8765 (not localhost): Bluesky sends your "
               "browser back to that address.",
               "Type your handle, for example name.bsky.social, and click Connect.",
               "Sign in at Bluesky if asked. The request should list only reading your "
               "timeline, search and feeds. Click Authorize; you come back here."],
     "alt_steps": ["Only if the OAuth sign-in fails (some self-hosted servers do not offer it): "
                   "in the Bluesky app, open Settings, then Privacy and security, then App "
                   "passwords, and add one named the server. Leave \"Allow access to your direct "
                   "messages\" off.",
                   "Paste your handle and the app password below and click Save and test. "
                   "the server signs in once and keeps only the session, never the password.",
                   "An app password is not limited by scopes: the server only ever calls the read "
                   "endpoints above, but OAuth is the read-only way."],
     "fields": [{"key": "handle", "label": "Handle", "placeholder": "name.bsky.social"},
                {"key": "app_password", "label": "App password",
                 "placeholder": "xxxx-xxxx-xxxx-xxxx", "secret": True}],
     "sources": ["Your home timeline", "Search"]},
    {"key": "github", "name": "GitHub", "state": "available", "flow": "paste",
     "blurb": "A fine-grained, read-only token you paste, for the releases of what you star "
              "on GitHub. GitHub's device flow lights up once an OAuth app's client id is set "
              "(written by hand in kranto.yaml; the steps below say where).",
     "scopes": ["token: public repositories, read-only, no permissions"]
               + [f"device flow: {s}" for s in GitHubProvider.scopes],
     "reads": "Which repositories you star (public), and their releases.",
     "never": "Never stars, follows, comments or reads private repositories. Its only use is "
              "GitHub's larger allowance for signed-in reads (5,000 an hour).",
     "revoke_at": "github.com, Settings, Developer settings, Personal access tokens (or, for "
                  "the device flow, Settings, Applications, Authorized OAuth Apps).",
     "expiry": "until the token's expiry date",
     "steps": ["On github.com open Settings, then Developer settings, then Personal access "
               "tokens, then Fine-grained tokens, and click Generate new token "
               "(https://github.com/settings/personal-access-tokens/new).",
               "Name it the server and pick an expiration (up to a year; paste a new one then).",
               "Resource owner: your account. Repository access: Public repositories "
               "(read-only).",
               "Permissions: add none. Public data needs no permission, and the server reads "
               "nothing else.",
               "Click Generate token, copy it, paste it below and click Save and test."],
     "device_steps": ["Register an OAuth app once: github.com, Settings, Developer settings, "
                      "OAuth Apps, New OAuth App (https://github.com/settings/applications/new)"
                      ".",
                      "Name the server; homepage https://github.com/iddv/kranto; callback URL "
                      "http://127.0.0.1:8765/ (the device flow does not use it). Tick Enable "
                      "Device Flow, then Register application.",
                      "Copy the Client ID. No client secret is needed: do not make one.",
                      "In kranto.yaml set connections: {github_client_id: <the id>} and "
                      "restart the server. A Sign in with GitHub button then appears here."],
     "fields": [{"key": "token", "label": "Fine-grained token",
                 "placeholder": "github_pat_...", "secret": True}],
     "sources": ["Releases of repositories you star"]},
    {"key": "youtube", "name": "YouTube", "state": "available", "flow": "client",
     "client_section": "1. Your Google Cloud project",
     "client_ready": "Save the client id and secret first.",
     "client_removed": "Removed the client id and secret.",
     "blurb": "Your own Google Cloud app, with guided steps: paste its client id and "
              "secret, then connect. For your subscriptions; API data is kept 30 days.",
     "scopes": list(YouTubeProvider.scopes),
     "reads": "Which channels you subscribe to, and their latest uploads.",
     "never": "Never subscribes, likes, comments or uploads. API data is kept at most 30 days, "
              "as YouTube's policies require.",
     "revoke_at": "myaccount.google.com, Security, Your connections to third-party apps and "
                  "services.",
     "expiry": "refreshed automatically",
     "steps": ["Open console.cloud.google.com and create a project named the server.",
               "APIs and services, Library: find YouTube Data API v3 and click Enable.",
               "Google Auth Platform (the OAuth consent screen), Get started: app name "
               "the server, your email for support and contact, audience External.",
               "Data access, Add or remove scopes: tick .../auth/youtube.readonly, then Save.",
               "Audience: click Publish app (In production). An app for your own use needs no "
               "verification; left in Testing, the sign-in expires every 7 days.",
               "Clients, Create client: application type Desktop app, name the server, Create. "
               "Copy the Client ID and the Client secret.",
               "Paste both below and click Save. They are kept encrypted like a token.",
               "Click Connect (with kranto open as localhost or 127.0.0.1), choose your "
               "account, and continue past the unverified-app warning (Advanced, then Go to "
               "the server). Allow viewing your YouTube account.",
               "Add Your subscriptions from Add source. Each fetch costs about 100 of the "
               "10,000 quota units a day."],
     "fields": [{"key": "client_id", "label": "Client ID",
                 "placeholder": "1234-abc.apps.googleusercontent.com"},
                {"key": "client_secret", "label": "Client secret", "placeholder": "GOCSPX-...",
                 "secret": True}],
     "sources": ["Your subscriptions"]},
    {"key": "producthunt", "name": "Product Hunt", "state": "available", "flow": "paste",
     "blurb": "A developer token you paste, for launches by topic through Product Hunt's API.",
     "scopes": list(ProductHuntProvider.scopes),
     "reads": "Public launches, filtered by topic, with their votes.",
     "never": "Never votes, comments or follows. Product Hunt's API is for non-commercial use.",
     "revoke_at": "producthunt.com/v2/oauth/applications: delete the token or the application.",
     "expiry": "no expiry",
     "steps": ["Sign in at producthunt.com and open the API dashboard "
               "(https://www.producthunt.com/v2/oauth/applications).",
               "Add an application: name the server, redirect URI http://127.0.0.1:8765/ (the "
               "form needs one; it is not used).",
               "On the application, click Create Token under Developer Token and copy it.",
               "Paste it below and click Save and test. Then add Launches by topic from Add "
               "source."],
     "fields": [{"key": "token", "label": "Developer token", "secret": True}],
     "sources": ["Launches by topic"]},
    {"key": "stackexchange", "name": "Stack Exchange", "state": "available", "flow": "paste",
     "blurb": "An app key you paste. Not a login: it raises the daily allowance for Search on a "
              "site from 300 requests to 10,000.",
     "scopes": list(StackExchangeProvider.scopes),
     "reads": "Public questions, through the API's search.",
     "never": "Never reads anything of your account, votes or posts: a key is not a login.",
     "revoke_at": "stackapps.com/apps/oauth: open the app and delete it.",
     "expiry": "no expiry",
     "steps": ["Sign in at stackapps.com and open https://stackapps.com/apps/oauth/register.",
               "Application name the server, description Personal reader, OAuth domain "
               "localhost, application website https://github.com/iddv/kranto. Leave client "
               "side OAuth off. Register.",
               "Copy the Key. The Client Secret is not needed.",
               "Paste the key below and click Save and test. Search on a site then uses it."],
     "fields": [{"key": "key", "label": "Key", "secret": True}],
     "sources": ["Search on a site"]},
    {"key": "reddit", "name": "Reddit", "state": "available", "flow": "paste",
     "blurb": "Your own Reddit app, approved by Reddit in your name: kranto reads your "
              "subreddits through Reddit's API as you. Kranto ships no key and runs no service.",
     "scopes": list(RedditProvider.scopes),
     "reads": "New and top posts of the subreddits you add, with their scores and top "
              "comments, every 3 hours, one request a second.",
     "never": "Your own app and your own account; kranto reads for you alone, keeps what it "
              "reads in your library under your retention, never republishes it, never trains "
              "on it, and drops what Reddit removes. Never posts, votes or messages.",
     "revoke_at": "reddit.com/prefs/apps: delete the app, or revoke it under your account's "
                  "authorized apps.",
     "expiry": "the refresh token lasts until you revoke it",
     "steps": ["Reddit's dates (its r/redditdev post of 2026-09-30): new requests for API "
               "access end on 31 Oct 2026; its feeds stop on 13 Nov 2026; apps that have not "
               "registered lose access from 12 Jan 2027; public access ends in March 2027.",
               "Request access with Reddit's Data Access Request form "
               "(https://support.reddithelp.com/hc/en-us/requests/new), for a script app in your "
               "own name: \"one person's own reading tool on my own machine; no redistribution, "
               "no training; a few hundred requests a day\". Whether a personal investing tool "
               "is commercial use is Reddit's to say.",
               "Once approved: at reddit.com/prefs/apps create the app, then make a refresh "
               "token for it (duration permanent, scopes read and identity).",
               "Paste the app's client id, its secret and the refresh token below, and click "
               "Save and test."],
     "fields": [{"key": "client_id", "label": "Client id"},
                {"key": "client_secret", "label": "Secret", "secret": True},
                {"key": "refresh_token", "label": "Refresh token", "secret": True}],
     "sources": ["Subreddit"]},
    {"key": "x", "name": "X / Twitter", "state": "available", "flow": "client",
     "redirect_host": "127.0.0.1",
     "client_section": "1. Your X developer app",
     "client_ready": "Save the client id first.",
     "client_removed": "Removed the client id.",
     "blurb": "Your own X developer app (a Native App: no secret), then a read-only sign-in. "
              "X bills your developer account per post read ($0.005; your own bookmarks and "
              "likes $0.001); Kranto counts every read on Settings › Spend.",
     "scopes": list(XProvider.scopes),
     "reads": "Your lists, your home timeline, a profile's posts, searches, your bookmarks and "
              "likes, as the sources you add from them.",
     "never": "Never posts, likes, reposts, follows or reads your messages. A grant wider than "
              "these read scopes is revoked and refused. Posts are kept 30 days by default and "
              "authors are never kept; nothing is shown to anyone else or used for training.",
     "revoke_at": "x.com, Settings and privacy, Security and account access, Apps and sessions, "
                  "Connected apps.",
     "expiry": "refreshed automatically (X's tokens last two hours)",
     "cost": "About $46 a month for 10 topics and one list of 200 accounts at the defaults "
             "(20 list posts a run, searches once a day); Test is one user read ($0.01).",
     "steps": ["Sign in at console.x.com (X's Developer Console) with your X account and accept "
               "the Developer Agreement.",
               "Buy credits and set a spending limit for the billing cycle. X bills per post "
               "read and stops answering at a zero balance; Kranto then says so on the source.",
               "Create an app, name the server. For the description, the use-case text: \"A "
               "personal reading tool. Reads posts from my own lists, searches, bookmarks and "
               "likes, has a language model sort them for my own research notes, keeps them "
               "on my machine for a limited time, never displays or redistributes them, never "
               "trains a model.\"",
               "User authentication settings: type Native App (public client), permissions "
               "Read, the callback URL exactly as this page prints it under 2. Connect "
               "(http://127.0.0.1, Kranto's port, /connections/x/callback), website "
               "https://github.com/iddv/kranto. Save.",
               "Keys and tokens: copy the OAuth 2.0 Client ID. A Native App has no client "
               "secret: do not make one. Paste the id below and click Save.",
               "Open Kranto as http://127.0.0.1 with its port (not localhost: X sends your "
               "browser back to exactly the callback), click Connect, and allow read access.",
               "Add X sources from Add source; a list of yours is the cheapest signal. Each "
               "source says what one run reads and costs; Settings › Spend shows the month "
               "and takes a cap (none by default)."],
     "fields": [{"key": "client_id", "label": "Client ID",
                 "placeholder": "the OAuth 2.0 Client ID of your Native App"}],
     "sources": ["A list of yours", "Your home timeline", "An account", "Search",
                 "Your bookmarks", "Your likes"]},
    {"key": "linkedin", "name": "LinkedIn", "state": "not_offered",
     "reason": "No API reads the feed or other people's posts outside partner programmes, and "
               "the User Agreement forbids scraping and automated access."},
    {"key": "mastodon_post", "name": "Mastodon (posting)", "state": "available",
     "flow": "paste", "writes": True,
     "blurb": "The one account Kranto posts as: Kranto drafts a post, and publishes it with "
              "this token only when you approve that post (Post toot). "
              "Separate from the read-only Mastodon connection.",
     "scopes": list(MastodonPostProvider.scopes),
     "reads": "Which account it is, and the instance's character limit.",
     "never": "Never posts without your approval, and never while the cub is in practice (the "
              "default: nothing is sent) or cubs.STOP exists. Never follows, boosts, favourites, "
              "deletes or reads your messages.",
     "revoke_at": "Preferences, then Development (a token you made) or Account, then "
                  "Authorized apps, on your instance.",
     "expiry": "no expiry",
     "steps": ["On your instance open Preferences, then Development, and click New "
               "application.",
               "Application name Kranto (posting). Scopes: untick everything, then tick only "
               "read:accounts and write:statuses. Submit.",
               "Open the application and copy Your access token.",
               "Paste your instance (for example mastodon.social) and the token below and "
               "click Save and test. Kranto names the connection @you@instance.",
               "A cub's posts are practice (nothing is sent) until you turn on Send for real."],
     "fields": [{"key": "instance", "label": "Instance", "placeholder": "mastodon.social"},
                {"key": "token", "label": "Access token", "secret": True}],
     "sources": []},
    SANITY_INFO,
]
INFO = {p["key"]: p for p in PROVIDER_INFO}
# Providers other packages register (each newsletter platform): key -> the Provider class.
REGISTERED: dict[str, type[Provider]] = {}


def register(info: dict, provider: type[Provider]) -> None:
    """A provider that lives with the package that uses it (a newsletter platform's module)
    joins the Connections page (``info``, the shape of ``PROVIDER_INFO``) and the registry."""
    if info["key"] not in INFO:
        PROVIDER_INFO.append(info)
        INFO[info["key"]] = info
    REGISTERED[info["key"]] = provider


def _conn_key(conn_id: int) -> str:
    return f"conn:{conn_id}"


class ConnectionAuth:
    """The ``HTTP.with_auth`` hook for one connection."""

    def __init__(self, connections: Connections, conn_id: int, host: str,
                 provider: Provider) -> None:
        self.connections, self.conn_id, self.host = connections, conn_id, host
        self.provider = provider
        self._entry: dict | None = None

    def headers(self, method: str, url: str) -> dict[str, str]:
        self._entry = self.connections.credentials(self.conn_id)
        return self.provider.headers(self._entry, method, url)

    def params(self) -> dict[str, str]:
        entry = self._entry or self.connections.credentials(self.conn_id)
        return self.provider.params(entry)

    def observe(self, response) -> bool:
        return self.provider.observe(response)

    @property
    def account_id(self) -> str | None:
        """The connected account's own id at the provider (X's numeric user id), for the
        timelines that name it; never a secret."""
        entry = self._entry or self.connections.credentials(self.conn_id)
        value = entry.get("user_id")
        return str(value) if value else None

    def refused(self) -> None:
        self.connections.mark_needs_login(
            self.conn_id, "the provider refused the token (HTTP 401); reconnect")


class Connections:
    def __init__(self, store: Store, data_dir: Path, http: HTTP, *,
                 machine_id: Path | None = None, enabled: bool = True,
                 github_client_id: str | None = None, clock=time.time) -> None:
        self.store = store
        self.http = http
        self.enabled = enabled
        self.vault = Vault(Path(data_dir) / "secrets",
                           **({"machine_id": machine_id} if machine_id else {}))
        self.providers: dict[str, Provider] = {
            "mastodon": MastodonProvider(http, self),
            "bluesky": BlueskyProvider(http, self),
            "github": GitHubProvider(http, self, client_id=github_client_id),
            "youtube": YouTubeProvider(http, self),
            "producthunt": ProductHuntProvider(http, self),
            "reddit": RedditProvider(http, self),
            "stackexchange": StackExchangeProvider(http, self),
            "x": XProvider(http, self),
            "mastodon_post": MastodonPostProvider(http, self),
            "sanity": SanityProvider(http, self),
            **{key: cls(http, self) for key, cls in REGISTERED.items()},
        }
        self.clock = clock
        self._refresh_lock = threading.Lock()
        self._touched: dict[int, float] = {}

    # -- availability -------------------------------------------------------------------

    def unavailable(self) -> str | None:
        """Why connections cannot be used here, or None."""
        if not self.enabled:
            return "connections.enabled is false in kranto.yaml"
        if not crypto_available():
            return "the cryptography package is missing: pip install 'kranto[connections]'"
        return None

    def _provider(self, provider: str) -> Provider:
        reason = self.unavailable()
        if reason:
            raise OAuthError(f"connected accounts are off: {reason}")
        if provider not in self.providers:
            raise OAuthError(f"{INFO.get(provider, {}).get('name', provider)} cannot be "
                             "connected in this version")
        return self.providers[provider]

    def instance_of(self, provider: str, value: str | None) -> str:
        """The instance a provider's connection is recorded under: the instance host
        for Mastodon, the provider's own name for one-account providers."""
        p = self.providers.get(provider)
        if p is not None and p.single:
            return p.default_instance
        return str(value or "").lower()

    def provider_info(self) -> list[dict]:
        """``PROVIDER_INFO`` with what is true right now: whether a client provider's
        own client (YouTube's project, X's app) is saved, whether GitHub's device flow is
        configured. Never a secret."""
        out = copy.deepcopy(PROVIDER_INFO)
        off = self.unavailable()
        for p in out:
            if p.get("flow") == "client" and p["key"] in self.providers:
                p["client_set"] = False
                if not off:
                    try:
                        p["client_set"] = self.providers[p["key"]].client() is not None
                    except VaultError:
                        p["client_set"] = False
            if p["key"] == "github":
                p["device"] = self.providers["github"].device_ready()
        return out

    # -- reading --------------------------------------------------------------------------

    def _state(self, conn_id: int) -> tuple[str | None, str | None, str | None]:
        """(state, note, at) of the latest state event."""
        row = self.store.query_one(
            "SELECT event, note, created_at FROM connection_events WHERE connection_id = ? "
            "AND event IN ('connected', 'needs_login', 'disconnected') ORDER BY id DESC LIMIT 1",
            (conn_id,))
        return (row["event"], row["note"], row["created_at"]) if row else (None, None, None)

    def current(self, provider: str, instance: str | None) -> dict | None:
        """The live connection for a provider and instance: the newest not disconnected."""
        for row in self.store.query(
                "SELECT * FROM connections WHERE provider = ? AND instance = ? "
                "ORDER BY id DESC", (provider, self.instance_of(provider, instance))):
            state, note, _ = self._state(row["id"])
            if state in ("connected", "needs_login"):
                return {**dict(row), "state": state, "note": note}
            if state == "disconnected":
                return None
        return None

    def get(self, conn_id: int) -> dict | None:
        row = self.store.query_one("SELECT * FROM connections WHERE id = ?", (conn_id,))
        if row is None:
            return None
        state, note, _ = self._state(conn_id)
        return {**dict(row), "state": state, "note": note}

    def accounts(self) -> list[dict]:
        """Live connections, for the Connections page: no secret, ever."""
        from ..library import list_sources
        from ..sources import needs, uses

        approved = [(s, needs(s.kind, s.params) or uses(s.kind))
                    for s in list_sources(self.store, "approved")]
        out = []
        for row in self.store.query("SELECT * FROM connections ORDER BY id"):
            state, note, at = self._state(row["id"])
            if state not in ("connected", "needs_login"):
                continue
            current = self.current(row["provider"], row["instance"])
            if current is None or current["id"] != row["id"]:
                continue
            tested = self.store.query_one(
                "SELECT note, created_at FROM connection_events WHERE connection_id = ? AND "
                "event = 'tested' ORDER BY id DESC LIMIT 1", (row["id"],))
            connected = self.store.query_one(
                "SELECT created_at FROM connection_events WHERE connection_id = ? AND "
                "event = 'connected' ORDER BY id LIMIT 1", (row["id"],))
            last_used = None
            if not self.unavailable():
                try:
                    last_used = (self.vault.get(_conn_key(row["id"])) or {}).get("last_used_at")
                except VaultError:
                    last_used = None
            using = [s for s, p in approved if p == row["provider"]
                     and self.instance_of(p, s.params.get("instance")) == row["instance"]]
            out.append({
                "id": row["id"], "provider": row["provider"],
                "provider_name": INFO.get(row["provider"], {}).get("name", row["provider"]),
                "instance": row["instance"], "account": row["account"],
                "scopes": ConnectionScopes.load(row["scopes"]).items, "state": state,
                "writes": bool(getattr(self.providers.get(row["provider"]), "writes", False)),
                "note": note if state == "needs_login" else None,
                "connected_at": connected["created_at"] if connected else row["created_at"],
                "state_at": at, "last_used_at": last_used,
                "last_test": dict(tested) if tested else None,
                "sources": [{"id": s.id, "label": s.label} for s in using],
            })
        return out

    def needs_you(self) -> int:
        return sum(1 for a in self.accounts() if a["state"] == "needs_login")

    def events(self, conn_id: int, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.store.query(
            "SELECT event, note, created_at FROM connection_events WHERE connection_id = ? "
            "ORDER BY id DESC LIMIT ?", (conn_id, limit))]

    # -- signing in: the browser flow ---------------------------------------------------------

    def start(self, provider: str, value: str, redirect_uri: str) -> tuple[str, int]:
        """Begin a browser sign-in: (the provider's authorize URL, the state row's id).
        ``value`` is what the person typed: a Mastodon instance, a Bluesky handle."""
        p = self._provider(provider)
        if not p.browser:
            raise OAuthError(f"{p.name} is connected by pasting a token, not by signing in")
        try:
            why = p.available()
            if why:
                raise OAuthError(why)
            instance = p.instance(value) if not p.single else p.default_instance
            started = oauth.start(self.store, self.vault, provider, instance, redirect_uri)
            url, extra = p.authorize(instance, value, redirect_uri, started.state,
                                     started.challenge)
            oauth.keep(self.vault, started.state_id, extra)
        except VaultError as exc:
            raise OAuthError(str(exc)) from None
        return url, started.state_id

    def finish(self, provider: str, cookie: str | None, query: dict) -> dict:
        """Complete a sign-in from the callback's query. Returns the new connection.

        The state is checked (and spent) before anything else, including a
        provider's error reply."""
        p = self._provider(provider)
        try:
            pending = oauth.consume(self.store, self.vault, provider, cookie, query.get("state"))
        except VaultError as exc:
            raise OAuthError(str(exc)) from None
        if query.get("error"):
            raise OAuthError(f"access was not granted at {p.name}; nothing was connected")
        try:
            grant = p.complete(pending, query)
        except (VaultError, SourceError) as exc:
            raise OAuthError(f"the sign-in could not be finished ({_short(exc)})") from None
        return self._record(provider, pending.instance, grant)

    # -- signing in: a pasted token or key --------------------------------------------------

    def paste(self, provider: str, fields: dict) -> dict:
        """Connect with a pasted credential (a token, a key, an app password): tested
        with one call before it is kept."""
        p = self._provider(provider)
        fields = {k: v for k, v in fields.items() if isinstance(v, str)}
        try:
            grant = p.paste(fields)
            instance = p.paste_instance(fields)
        except SourceError as exc:
            raise OAuthError(f"the credential could not be checked ({_short(exc)})") from None
        return self._record(provider, instance, grant)

    def set_client(self, provider: str, fields: dict) -> None:
        """Keep the owner's own OAuth client (YouTube's Google Cloud project)."""
        p = self._provider(provider)
        if not hasattr(p, "set_client"):
            raise OAuthError(f"{p.name} needs no client of your own")
        try:
            p.set_client(fields)
        except VaultError as exc:
            raise OAuthError(str(exc)) from None

    def clear_client(self, provider: str) -> None:
        p = self._provider(provider)
        if not hasattr(p, "clear_client"):
            raise OAuthError(f"{p.name} needs no client of your own")
        try:
            p.clear_client()
        except VaultError as exc:
            raise OAuthError(str(exc)) from None

    # -- signing in: GitHub's device flow ----------------------------------------------------

    def device_start(self, provider: str) -> tuple[str, dict]:
        """Ask for a device code: (the browser's cookie, what the page shows)."""
        p = self._provider(provider)
        if not hasattr(p, "device_start"):
            raise OAuthError(f"{p.name} has no device sign-in")
        info = p.device_start()
        now = self.clock()
        try:
            cookie = oauth.start_device(self.store, self.vault, provider, p.default_instance, {
                "device_code": info["device_code"], "interval": info["interval"],
                "next_poll_at": now + info["interval"]})
        except VaultError as exc:
            raise OAuthError(str(exc)) from None
        return cookie, {k: info[k] for k in ("user_code", "verification_uri", "interval",
                                             "expires_in")}

    def device_poll(self, provider: str, cookie: str | None) -> dict:
        """One poll, never faster than the provider's interval: ``{state, interval}``
        with state pending, connected (with ``account``), denied or expired."""
        p = self._provider(provider)
        if not hasattr(p, "device_poll"):
            raise OAuthError(f"{p.name} has no device sign-in")
        try:
            state_id, entry = oauth.device(self.store, self.vault, provider, cookie)
            now = self.clock()
            interval = int(entry.get("interval") or 5)
            if now < float(entry.get("next_poll_at") or 0):
                return {"state": "pending", "interval": interval}
            try:
                result = p.device_poll(entry["device_code"])
            except (OAuthError, SourceError):
                oauth.spend(self.store, self.vault, state_id)
                raise
            if result["state"] in ("pending", "slow_down"):
                if result["state"] == "slow_down":
                    # GitHub's slow_down adds five seconds to the interval, for good.
                    interval = max(int(result.get("interval") or 0), interval + 5)
                oauth.keep(self.vault, state_id, {"interval": interval,
                                                  "next_poll_at": now + interval})
                return {"state": "pending", "interval": interval}
            oauth.spend(self.store, self.vault, state_id)
            if result["state"] != "granted":
                return {"state": result["state"], "interval": interval}
        except VaultError as exc:
            raise OAuthError(str(exc)) from None
        except SourceError as exc:
            raise OAuthError(f"the sign-in could not be finished ({_short(exc)})") from None
        conn = self._record(provider, p.default_instance, result["grant"])
        return {"state": "connected", "account": conn["account"], "interval": interval}

    # -- recording -----------------------------------------------------------------------------

    def _record(self, provider: str, instance: str, grant: Grant) -> dict:
        p = self.providers.get(provider)
        exclusive = p is not None and p.exclusive
        previous = self.live(provider) if exclusive else \
            [c for c in [self.current(provider, instance)] if c is not None]
        now = iso(utcnow())
        conn_id = self.store.insert("connections", {
            "provider": provider, "instance": instance, "account": grant.account,
            "scopes": ConnectionScopes.write(list(grant.scopes)), "created_at": now})
        try:
            self.vault.put(_conn_key(conn_id), {**grant.secrets, "last_used_at": None})
        except VaultError as exc:
            self._event(conn_id, "disconnected", "the token could not be stored; nothing kept")
            raise OAuthError(str(exc)) from None
        self._event(conn_id, "connected", f"{grant.account}, {_scopes_word(p, len(grant.scopes))}")
        for old in previous:
            # The new sign-in replaces the old one for this account's instance (for a posting
            # account, whatever its instance: one per Kranto).
            self._drop(old["id"], "replaced by a new sign-in")
        return {**self.get(conn_id), "said": grant.note or None}

    def live(self, provider: str) -> list[dict]:
        """Every live connection of ``provider``, newest first, whatever the instance."""
        out = []
        for inst in [r["instance"] for r in self.store.query(
                "SELECT instance, MAX(id) AS id FROM connections WHERE provider = ? "
                "GROUP BY instance ORDER BY id DESC", (provider,))]:
            conn = self.current(provider, inst)
            if conn is not None:
                out.append(conn)
        return out

    def _event(self, conn_id: int, event: str, note: str | None) -> None:
        self.store.insert("connection_events", {"connection_id": conn_id, "event": event,
                                                "note": note, "created_at": iso(utcnow())})

    # -- using a connection ----------------------------------------------------------------

    def http_for(self, provider: str, instance: str | None, http: HTTP) -> HTTP:
        """``http`` with the connection's credentials added at send time. Raises a
        transient ``SourceError`` marked ``needs_login`` when no usable connection exists."""
        conn = self.current(provider, instance)
        name = INFO.get(provider, {}).get("name", provider)
        if conn is None:
            p = self.providers.get(provider)
            where = f" on {instance}" if p is not None and not p.single else ""
            raise SourceError(f"needs login: no {name} account{where} is connected",
                              needs_login=True)
        if conn["state"] == "needs_login":
            raise SourceError(f"needs login: the {name} connection for {conn['account']} "
                              f"needs you to reconnect", needs_login=True)
        reason = self.unavailable()
        if reason:
            raise SourceError(f"needs login: {reason}", needs_login=True)
        return self._authed(conn, http)

    def _authed(self, conn: dict, http: HTTP) -> HTTP:
        p = self.providers[conn["provider"]]
        try:
            entry = self.vault.get(_conn_key(conn["id"])) or {}
        except VaultError as exc:
            raise SourceError(f"needs login: {exc}", needs_login=True) from None
        return http.with_auth(ConnectionAuth(self, conn["id"],
                                             p.api_host(conn["instance"], entry), p))

    def credentials(self, conn_id: int) -> dict:
        """The connection's vault entry, refreshed first if its token expires within
        five minutes. Raises ``SourceError`` (needs_login) if it cannot be had."""
        try:
            entry = self.vault.get(_conn_key(conn_id))
        except VaultError as exc:
            raise SourceError(f"needs login: {exc}", needs_login=True) from None
        if not entry or not (entry.get("access_token") or entry.get("key")):
            self.mark_needs_login(conn_id, "its token is missing from data/secrets; reconnect")
            raise SourceError("needs login: the connection's token is missing", needs_login=True)
        expires = entry.get("expires_at")
        if expires is not None and expires - self.clock() < REFRESH_WITHIN_SECONDS:
            entry = self._refresh(conn_id)
        self._touch(conn_id)
        return entry

    def _refresh(self, conn_id: int) -> dict:
        conn = self.get(conn_id)
        provider = self.providers.get(conn["provider"]) if conn is not None else None
        # A provider that rotates its refresh token (X) is refreshed under the vault's file
        # lock, read to write: another process that refreshes at the same moment waits, then
        # finds the new pair instead of spending the dead token.
        across = self.vault.locked() if getattr(provider, "rotates_refresh", False) \
            else contextlib.nullcontext()
        with self._refresh_lock, across:
            entry = self.vault.get(_conn_key(conn_id)) or {}
            expires = entry.get("expires_at")
            if expires is None or expires - self.clock() >= REFRESH_WITHIN_SECONDS:
                return entry  # another thread or process refreshed it while this one waited
            if conn is None or not entry.get("refresh_token") or provider is None:
                self.mark_needs_login(conn_id, "the token expired and cannot be refreshed")
                raise SourceError("needs login: the token expired", needs_login=True)
            try:
                changes = provider.refresh(conn["instance"], entry)
            except (OAuthError, SourceError):
                self.mark_needs_login(conn_id, "refreshing the token failed; reconnect")
                raise SourceError("needs login: refreshing the token failed",
                                  needs_login=True) from None
            return self.vault.update(_conn_key(conn_id), **changes) or entry

    def _touch(self, conn_id: int) -> None:
        now = self.clock()
        if now - self._touched.get(conn_id, 0.0) < TOUCH_EVERY_SECONDS:
            return
        self._touched[conn_id] = now
        try:
            self.vault.update(_conn_key(conn_id), last_used_at=iso(utcnow()))
        except VaultError:
            log.warning("could not record when connection %s was last used", conn_id)

    def mark_needs_login(self, conn_id: int, note: str) -> None:
        state, _, _ = self._state(conn_id)
        if state == "connected":
            self._event(conn_id, "needs_login", note)

    # -- test and disconnect -----------------------------------------------------------------

    def test(self, conn_id: int) -> dict:
        """One identity call. Records a ``tested`` event, or ``needs_login`` if refused."""
        conn = self.get(conn_id)
        if conn is None or conn["state"] not in ("connected", "needs_login"):
            raise OAuthError("no such connection")
        p = self._provider(conn["provider"])
        try:
            http = self._authed(conn, self.http)
            entry = self.credentials(conn_id)
            account = p.identify(http, conn["instance"], entry)
        except SourceError as exc:
            self._event(conn_id, "tested", f"failed: {_short(exc)}")
            return {"ok": False, "message": _short(exc)}
        except OAuthError as exc:
            self._event(conn_id, "tested", f"failed: {exc}")
            return {"ok": False, "message": str(exc)}
        self._event(conn_id, "tested", f"ok: {account}")
        if conn["state"] == "needs_login":
            self._event(conn_id, "connected", "the token works again")
        scopes = len(ConnectionScopes.load(conn["scopes"]).items)
        return {"ok": True, "message": f"Signed in as {account}, "
                                       f"{_scopes_word(p, scopes)}."}

    def disconnect(self, conn_id: int) -> str:
        """Revoke at the provider where it can, then delete the token here."""
        conn = self.get(conn_id)
        if conn is None or conn["state"] not in ("connected", "needs_login"):
            raise OAuthError("no such connection")
        return self._drop(conn_id, None)

    def _drop(self, conn_id: int, why: str | None) -> str:
        conn = self.get(conn_id)
        revoked = False
        try:
            entry = self.vault.get(_conn_key(conn_id))
        except VaultError:
            entry = None
        provider = self.providers.get(conn["provider"])
        if entry and provider is not None:
            try:
                revoked = provider.revoke(conn["instance"], entry)
            except (OAuthError, SourceError):
                revoked = False
        try:
            self.vault.delete(_conn_key(conn_id))
        except VaultError:
            log.warning("could not delete connection %s's token from the vault", conn_id)
        where = INFO.get(conn["provider"], {}).get("revoke_at", "the site's settings")
        note = ("revoked at the provider and deleted here" if revoked
                else f"deleted here; revoke it on the site too: {where}")
        self._event(conn_id, "disconnected", f"{why}; {note}" if why else note)
        return note

    # -- housekeeping ----------------------------------------------------------------------

    def cleanup(self, now: datetime | None = None) -> int:
        if self.unavailable():
            return 0
        try:
            return oauth.cleanup(self.store, self.vault, now=now)
        except VaultError:
            return 0


def _scopes_word(provider: Provider | None, n: int) -> str:
    """"3 read-only scopes", or "2 scopes" for a credential that sends."""
    kind = "" if provider is not None and provider.writes else "read-only "
    return f"{n} {kind}scope{'' if n == 1 else 's'}"


def _short(exc: Exception) -> str:
    """An error's text for a page or an event note: the server's own wording, scrubbed,
    without a query string."""
    from ..scrub import scrub

    text = str(exc)
    if isinstance(exc, SourceError):
        text = text.split(": ", 1)[-1] if text.startswith("https://") else text
    return scrub(text)[:300]


# The newsletter platforms register their providers (``register``) as their package loads.
from .. import newsletter as _newsletter  # noqa: E402,F401
