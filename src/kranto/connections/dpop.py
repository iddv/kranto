"""DPoP proofs (RFC 9449) with an ES256 key, as AT Protocol OAuth requires.

Each connection has its own P-256 key, made at sign-in and kept in the vault
with the token (PEM). Every request to the authorization server or the PDS
carries a fresh proof: a JWT signed with that key, naming the method, the URL
(without its query), a unique id, the time, the server's latest nonce and,
for a resource request, a hash of the access token. Needs the cryptography
package, like the vault.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlsplit, urlunsplit


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _ec():
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    return ec, hashes, serialization, decode_dss_signature


def new_key() -> str:
    """A new P-256 private key, PEM (PKCS#8)."""
    ec, _, serialization, _ = _ec()
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


def _load(pem: str):
    _, _, serialization, _ = _ec()
    return serialization.load_pem_private_key(pem.encode(), password=None)


def public_jwk(pem: str) -> dict:
    numbers = _load(pem).public_key().public_numbers()
    return {"kty": "EC", "crv": "P-256", "x": _b64(numbers.x.to_bytes(32, "big")),
            "y": _b64(numbers.y.to_bytes(32, "big"))}


def htu(url: str) -> str:
    """The URL a proof names: scheme, host and path, no query or fragment."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def proof(pem: str, method: str, url: str, *, nonce: str | None = None,
          access_token: str | None = None, now: float | None = None) -> str:
    """A DPoP proof JWT for one request."""
    ec, hashes, _, decode_dss_signature = _ec()
    header = {"typ": "dpop+jwt", "alg": "ES256", "jwk": public_jwk(pem)}
    payload = {"jti": secrets.token_urlsafe(16), "htm": method.upper(), "htu": htu(url),
               "iat": int(now if now is not None else time.time())}
    if nonce:
        payload["nonce"] = nonce
    if access_token:
        payload["ath"] = _b64(hashlib.sha256(access_token.encode()).digest())
    signing_input = (_b64(json.dumps(header, separators=(",", ":")).encode()) + "."
                     + _b64(json.dumps(payload, separators=(",", ":")).encode()))
    der = _load(pem).sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return signing_input + "." + _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
