"""Remove personal data and secrets from third-party text before anything else sees it.

Everything a source returns passes through here when an ``Item`` is built, so
no prompt to a model provider, no row in the library and no log line ever holds
what this catches. It is deliberately simple and deterministic: a
set of patterns, each replaced by a label such as ``[email]``. It is not
perfect, and it does not need to be; it removes the common cases before they
can be shared with a third party, and the judge prompt asks the model not to
repeat personal details that slip through.

Card numbers are only replaced when they pass the Luhn check, so ordinary long
numbers (benchmarks, counts, IDs) survive.
"""

from __future__ import annotations

import re
from collections import Counter

# Order matters: secrets and emails before the looser username and phone patterns.
_SECRETS = [
    re.compile(r"-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----.{0,20000}?-----END [A-Z ]{0,20}"
               r"PRIVATE KEY-----", re.S),
    # OpenAI, OpenRouter and Anthropic keys
    re.compile(r"\bsk-(?:or-v1-|ant-|proj-)?[A-Za-z0-9_-]{20,200}"),
    re.compile(r"\bxai-[A-Za-z0-9]{20,200}"),                         # xAI keys
    # Search backends' keys: Tavily's, Brave's. Exa's is a bare UUID, which
    # third-party text is full of; it never leaves Kranto's process, and setup refuses to echo it.
    re.compile(r"\btvly-(?:dev-|prod-)?[A-Za-z0-9]{20,200}"),
    re.compile(r"\bBSA[A-Za-z0-9_-]{24,200}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),                     # AWS access key ids
    # GitHub tokens, the stateless ghs_<app>_<jwt> form of an installation token included
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_.-]{16,4000}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,255}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,255}\b"),                  # Slack tokens
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),                         # Google API keys
    # JWTs
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,2000}\.eyJ[A-Za-z0-9_-]{8,2000}\.[A-Za-z0-9_-]{8,2000}"),
    # Connected accounts: Google OAuth access tokens; any
    # bearer token in an Authorization header (Mastodon, Product Hunt and others
    # have no prefix of their own); OAuth secrets in a query string or form body;
    # Bluesky app passwords (four groups of four, with digits in them: a phrase
    # such as self-host-your-data is not one).
    re.compile(r"\bya29\.[A-Za-z0-9_-]{20,2000}"),
    re.compile(r"(?i)\b(?:authorization|dpop)\s*[:=]\s*(?:bearer|dpop|token)?\s*"
               r"[A-Za-z0-9._~+/=-]{12,4000}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,4000}"),
    re.compile(r"(?i)\b(?:client_secret|access_token|refresh_token|code_verifier|"
               r"app_password|device_code)=[^&\s\"']{6,4000}"),
    # An app key in a query string (Stack Exchange's ``key``).
    re.compile(r"(?<=[?&])key=[^&\s\"']{6,4000}"),
    re.compile(r"\b(?=[a-z2-7-]{0,17}[2-7][a-z2-7-]{0,17}[2-7])"
               r"[a-z2-7]{4}-[a-z2-7]{4}-[a-z2-7]{4}-[a-z2-7]{4}\b"),
]
# Every repetition is bounded: an unbounded run before "@" made a 1.5 MB title
# without one take minutes (each start position scanned to the end).
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}")
# Not part of a decimal number: a digit run after "0." once passed the Luhn check.
_CARD = re.compile(r"(?<![\d.])\b(?:\d[ -]?){12,18}\d\b(?![.\d])")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")
_PHONE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)|\d{2,4})[ .-]\d{3,4}[ .-]\d{3,4}(?![\w.])"
    r"|(?<![\w.])\+\d{9,14}(?![\w.])"
)
# u/name and /u/name (Reddit), @name (most social platforms). A leading word
# character rules out emails and decorators like foo@bar; a following "/" rules
# out npm package scopes such as @vercel/gateway, common in developer sources.
_USER = re.compile(
    r"(?<![\w/])/?u/[A-Za-z0-9_-]{3,20}\b"
    r"|(?<![\w@])@[A-Za-z0-9_][A-Za-z0-9_.-]{1,30}[A-Za-z0-9_](?![\w.-]*/)(?!\w)"
)


def _luhn(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def secret_shaped(text: str) -> bool:
    """Whether ``text`` holds something shaped like a key or a token (the secret patterns
    only, not personal data): a cub's setting never holds one."""
    return bool(text) and any(p.search(text) for p in _SECRETS)


def scrub(text: str, counts: Counter | None = None) -> str:
    """``text`` with personal data and secrets replaced by labels.

    ``counts``, if given, is incremented per kind replaced (never the content).
    """
    if not text:
        return text
    counts = counts if counts is not None else Counter()

    def sub(pattern: re.Pattern, label: str, s: str, check=None) -> str:
        def repl(m: re.Match) -> str:
            if check is not None and not check(m.group(0)):
                return m.group(0)
            counts[label] += 1
            return f"[{label}]"
        return pattern.sub(repl, s)

    for pattern in _SECRETS:
        text = sub(pattern, "secret", text)
    text = sub(_EMAIL, "email", text)
    text = sub(_CARD, "card", text, check=lambda s: _luhn(re.sub(r"\D", "", s)))
    text = sub(_SSN, "ssn", text)
    text = sub(_IBAN, "iban", text)
    text = sub(_PHONE, "phone", text)
    text = sub(_USER, "user", text)
    return text
