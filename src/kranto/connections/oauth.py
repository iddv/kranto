"""State and PKCE for browser sign-ins (section 3.3).

``POST /connections/<provider>/start`` creates a state: 32 random bytes, sent to
the provider in the authorize URL and kept by the browser in an ``afk_oauth``
cookie (HttpOnly, SameSite=Lax) holding the state row's id. The library keeps a
SHA-256 of the state, never the state; the PKCE verifier is kept in the vault.

``GET /connections/<provider>/callback`` is accepted only when the state row
exists, is for that provider, is under ``STATE_TTL`` old, has not been used, and
its hash matches the ``state`` the provider sent back; the row is then marked
used, whatever happens next. Rows older than ``KEEP`` are removed with their
verifiers.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..store import Store, iso, utcnow
from .vault import Vault

STATE_TTL = timedelta(minutes=10)
KEEP = timedelta(hours=1)


class OAuthError(Exception):
    """A sign-in cannot continue. The message is the server's own wording, safe to show."""


@dataclass(frozen=True)
class Started:
    state_id: int
    state: str
    challenge: str


@dataclass(frozen=True)
class Pending:
    """A state that passed every check: what the callback needs to finish."""

    state_id: int
    provider: str
    instance: str
    redirect_uri: str
    verifier: str
    # What the provider kept with the state for its callback (Bluesky: the DPoP
    # key, the authorization server, the account's DID and PDS).
    extra: dict = field(default_factory=dict, repr=False)


def pkce_pair() -> tuple[str, str]:
    """A PKCE ``(code_verifier, code_challenge)`` with the S256 method (RFC 7636)."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.decode().rstrip("=")


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _key(state_id: int) -> str:
    return f"oauth:{state_id}"


def start(store: Store, vault: Vault, provider: str, instance: str, redirect_uri: str,
          *, now: datetime | None = None) -> Started:
    now = now or utcnow()
    cleanup(store, vault, now=now)
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    state_id = store.insert("oauth_states", {
        "provider": provider, "instance": instance, "state_hash": _hash(state),
        "redirect_uri": redirect_uri, "created_at": iso(now), "used_at": None})
    vault.put(_key(state_id), {"verifier": verifier})
    return Started(state_id, state, challenge)


def consume(store: Store, vault: Vault, provider: str, cookie: str | None, state: str | None,
            *, now: datetime | None = None) -> Pending:
    """Check a callback's state against the cookie's row, and mark the row used.

    Refuses (``OAuthError``) a missing, unknown, used, expired or mismatched state."""
    now = now or utcnow()
    if not cookie or not state:
        raise OAuthError("the sign-in had no state; start again from Connections")
    try:
        state_id = int(cookie)
    except ValueError:
        raise OAuthError("the sign-in's cookie is not one the server set; start again") from None
    row = store.query_one("SELECT * FROM oauth_states WHERE id = ?", (state_id,))
    if row is None or row["provider"] != provider:
        raise OAuthError("this sign-in is not one the server started, or it was cleaned up; "
                         "start again from Connections")
    # Marked used before anything else is checked: a state gets one attempt. The
    # claim is one conditional UPDATE, so two callbacks racing on the same state
    # cannot both pass.
    with store.tx() as conn:
        claimed = conn.execute("UPDATE oauth_states SET used_at = ? WHERE id = ? "
                               "AND used_at IS NULL", (iso(now), state_id)).rowcount
    if not claimed:
        raise OAuthError("this sign-in was already used; start again from Connections")
    created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
    if now - created > STATE_TTL:
        raise OAuthError("the sign-in took longer than 10 minutes; start again")
    if not hmac.compare_digest(row["state_hash"], _hash(state)):
        raise OAuthError("the sign-in's state does not match; start again from Connections")
    entry = vault.get(_key(state_id)) or {}
    vault.delete(_key(state_id))
    if not entry.get("verifier"):
        raise OAuthError("the sign-in's verifier is gone; start again from Connections")
    verifier = entry.pop("verifier")
    return Pending(state_id, provider, row["instance"], row["redirect_uri"], verifier, entry)


def keep(vault: Vault, state_id: int, extra: dict) -> None:
    """Keep what a provider's callback needs with the state's verifier, in the vault."""
    if extra:
        vault.update(_key(state_id), **extra)


# -- the device flow (GitHub) ----------------------------------------------------------------
#
# No redirect comes back, so the browser holds the state itself: the cookie is
# ``<row id>.<state>`` and each poll is checked against the row's hash. The
# device code is kept in the vault with the row; the row is spent when the
# account is connected or the code is refused.

DEVICE_TTL = timedelta(minutes=15)


def start_device(store: Store, vault: Vault, provider: str, instance: str, extra: dict,
                 *, now: datetime | None = None) -> str:
    """A new device sign-in; returns the cookie value for the browser."""
    now = now or utcnow()
    cleanup(store, vault, now=now)
    state = secrets.token_urlsafe(32)
    state_id = store.insert("oauth_states", {
        "provider": provider, "instance": instance, "state_hash": _hash(state),
        "redirect_uri": "device", "created_at": iso(now), "used_at": None})
    vault.put(_key(state_id), {"verifier": "device", **extra})
    return f"{state_id}.{state}"


def device(store: Store, vault: Vault, provider: str, cookie: str | None,
           *, now: datetime | None = None) -> tuple[int, dict]:
    """The device sign-in a poll belongs to: (row id, what was kept). Refuses a
    missing, unknown, used, expired or mismatched cookie, without spending it."""
    now = now or utcnow()
    state_id_text, _, state = (cookie or "").partition(".")
    if not state_id_text or not state:
        raise OAuthError("the sign-in had no state; start again from Connections")
    try:
        state_id = int(state_id_text)
    except ValueError:
        raise OAuthError("the sign-in's cookie is not one the server set; start again") from None
    row = store.query_one("SELECT * FROM oauth_states WHERE id = ?", (state_id,))
    if row is None or row["provider"] != provider or row["redirect_uri"] != "device":
        raise OAuthError("this sign-in is not one the server started, or it was cleaned up; "
                         "start again from Connections")
    if row["used_at"]:
        raise OAuthError("this sign-in was already used; start again from Connections")
    if not hmac.compare_digest(row["state_hash"], _hash(state)):
        raise OAuthError("the sign-in's state does not match; start again from Connections")
    created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
    if now - created > DEVICE_TTL:
        spend(store, vault, state_id, now=now)
        raise OAuthError("the code expired after 15 minutes; start again")
    entry = vault.get(_key(state_id)) or {}
    if not entry.get("device_code"):
        raise OAuthError("the sign-in's device code is gone; start again from Connections")
    return state_id, entry


def spend(store: Store, vault: Vault, state_id: int, *, now: datetime | None = None) -> None:
    store.query("UPDATE oauth_states SET used_at = ? WHERE id = ?",
                (iso(now or utcnow()), state_id))
    vault.delete(_key(state_id))


def cleanup(store: Store, vault: Vault, *, now: datetime | None = None) -> int:
    """Remove states older than ``KEEP``, and their verifiers. Returns how many."""
    cutoff = iso((now or utcnow()) - KEEP)
    old = [r["id"] for r in store.query("SELECT id FROM oauth_states WHERE created_at < ?",
                                        (cutoff,))]
    if old:
        vault.delete(*(_key(i) for i in old))
        store.query(f"DELETE FROM oauth_states WHERE id IN ({','.join('?' * len(old))})",
                    tuple(old))
    return len(old)
