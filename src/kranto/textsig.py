"""Signatures of an item's own text, for finding the same text again.

Deterministic and local: no model, no embedding. An item's title and the start
of its body are normalised, cut into overlapping word shingles, and summarised
as a MinHash signature: ``PERMUTATIONS`` minimum hash values, one per hash
function. The fraction of positions on which two signatures agree estimates
the Jaccard similarity of the two shingle sets (Broder, 1997). A signature is
a fixed 512 bytes of hash values; it holds no text and cannot be turned back
into any.

This compares the text a source supplied, before the judge sees it. The stored
observation embedding is the wrong place for it: the judge rewords the same
item differently each time, and a cosine of 0.95 on observation embeddings
reached only 57% of same-URL pairs and 44% of crossposts.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata

import numpy as np

PERMUTATIONS = 128
SHINGLE_WORDS = 3
# Recorded with every stored signature. Signatures made with different settings
# or normalisation are never compared, as embeddings from different models are not.
METHOD = "minhash128-w3-b1000-v1"
# The start of the body: enough to tell a crosspost from a different post that
# opens the same way, short enough that a long thread's comments or a page's
# footer do not dilute it.
BODY_CHARS = 1000

# Text a feed puts in place of content it does not carry. Bluesky's RSS writes
# this for every quote post: in the #63 benchmark library two different posts
# matched on it alone.
PLACEHOLDERS = ("[contains quote post or other embedded content]",)
_TAG = re.compile(r"<[^>]{0,2000}>")
_URL = re.compile(r"https?://\S+|www\.\S+")
_WORD = re.compile(r"\w+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")

# Fixed multipliers and offsets for the hash functions, odd so each is a
# bijection on 64-bit integers. Generated once from a fixed seed: signatures
# written by one version compare with signatures written by the next.
_rng = np.random.default_rng(35)
_A = (_rng.integers(1, 2**63 - 1, PERMUTATIONS, dtype=np.uint64) * np.uint64(2)
      + np.uint64(1))
_B = _rng.integers(0, 2**63 - 1, PERMUTATIONS, dtype=np.uint64)
del _rng


def normalise(text: str) -> list[str]:
    """Lowercase words, without markup or URLs (the URL is compared on its own, #34).

    Markup goes first: an escaped link (``https:&#x2F;&#x2F;...``) is otherwise
    a run of words ("https", "x2f", "rel", "nofollow") that every such item
    shares."""
    text = html.unescape(html.unescape(text or ""))
    text = unicodedata.normalize("NFKC", _TAG.sub(" ", text)).lower()
    for placeholder in PLACEHOLDERS:
        text = text.replace(placeholder, " ")
    return _WORD.findall(_URL.sub(" ", text))


def item_text(title: str, body: str, body_chars: int = BODY_CHARS) -> str:
    return f"{title or ''}\n{(body or '')[:body_chars]}"


def shingles(words: list[str], k: int = SHINGLE_WORDS) -> set[str]:
    if not words:
        return set()
    if len(words) <= k:
        return {" ".join(words)}
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def _hash64(values: set[str]) -> np.ndarray:
    return np.array(
        [int.from_bytes(hashlib.blake2b(v.encode(), digest_size=8).digest(), "little")
         for v in sorted(values)],
        dtype=np.uint64,
    )


def signature(text: str, k: int = SHINGLE_WORDS) -> np.ndarray | None:
    """MinHash signature (uint32, ``PERMUTATIONS`` long) of ``text``; None when it has
    no words to compare."""
    grams = shingles(normalise(text), k)
    if not grams:
        return None
    h = _hash64(grams)
    # Multiply-shift hashing: (a*x + b) mod 2^64, top 32 bits. numpy's uint64
    # arithmetic wraps, which is exactly the modulus wanted.
    with np.errstate(over="ignore"):
        mixed = (h[None, :] * _A[:, None] + _B[:, None]) >> np.uint64(32)
    return mixed.min(axis=1).astype(np.uint32)


def similarity(sig: np.ndarray, others: np.ndarray) -> np.ndarray:
    """Estimated Jaccard similarity of ``sig`` with each row of ``others``."""
    if len(others) == 0:
        return np.zeros(0, dtype=np.float32)
    return (others == sig[None, :]).mean(axis=1).astype(np.float32)


def numbers(text: str) -> tuple[str, ...]:
    """The numbers in ``text``, in order: what tells one templated item from the next
    (a market's threshold, a release's version, a date)."""
    return tuple(_NUMBER.findall(unicodedata.normalize("NFKC", _URL.sub(" ", text or ""))))


def to_blob(sig: np.ndarray) -> bytes:
    return np.asarray(sig, dtype=np.uint32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.uint32)
