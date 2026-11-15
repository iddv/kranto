"""A refused model key is one blocking incident.

A provider that answers 401, 402 or 403, or says the key expired, is invalid or has no credit,
stops every kind that calls a model: reading the sources, the idea cards, a cub's run. Said as
one Fix row a kind, ranked like any other chore, it went unseen for two days. Here
such an error is classed ``auth:<provider>`` from its words, and the activity read folds every
kind it breaks into one incident a provider, from the **first** failure, with the verb that
fixes it: Renew the key.

It goes when it is fixed, whatever kind fixed it: a later successful call to the same
provider, a passing key test, or the owner's Dismiss. A 402 for credit too low for the calls in
flight is "low credit": the key works and the calls try again, so it never stops anything; a 402
of an empty balance is "out of credit".

The words come from the metered client's ``FatalLLMError`` ("HTTP 401 from <base url>: …",
"no API key: set $X") and from a cub's host error, which carries that message after
"the model did not answer: FatalLLMError". An older cub error that names only the class is
folded into an incident another kind already shows.
"""

from __future__ import annotations

import re
from typing import Any

# where the model key is set (Settings › Watching, its "Watching model" row)
KEY_HREF = "#/settings/watching?sel=ekey"
KEY_PLACE = "Settings › Watching"
VERB = "Renew the key"

# (a word in the error, the provider's id, its name)
PROVIDERS = (
    ("openrouter", "openrouter", "OpenRouter"),
    ("anthropic", "anthropic", "Claude API"),
    ("x.ai", "xai", "xAI"),
    ("xai_api_key", "xai", "xAI"),
    ("claude code", "claude_code", "Claude Code"),
)

_HTTP = re.compile(r"\bHTTP (40[123]) from (\S+?):?(?:\s|$)")
_MISSING = re.compile(r"no API key: set \$?([A-Z][A-Z0-9_]*)")
_KEY_WORDS = re.compile(
    r"api[ _-]?key (?:has )?expired|key (?:is )?expired|invalid (?:x-)?api[ _-]?key|"
    r"incorrect api key|invalid authentication|authentication[_ ]error|unauthori[sz]ed|"
    r"insufficient (?:credits?|balance|funds|quota)|no credits?|credit balance is too low",
    re.I)
_CLASS_ONLY = re.compile(r"did not answer: FatalLLMError\s*\.?\s*$")
# a provider's credit too low for the calls in flight (OpenRouter's 402 "would exceed your
# available credits given your current in-flight requests"): the key works, the calls wait and
# are tried again (#488: it read "refused, stopped until renewed" for a day of good calls)
_SQUEEZE = re.compile(r"in-flight requests|exceed your available credits", re.I)

# the causes that stop until the owner acts; "low credit" waits and tries again by itself
LOW_CREDIT = "low credit"


def _provider(text: str) -> tuple[str, str]:
    low = text.lower()
    for word, pid, name in PROVIDERS:
        if word in low:
            return pid, name
    m = _HTTP.search(text)
    if m:
        host = re.sub(r"^https?://", "", m.group(2)).split("/")[0].split(":")[0]
        if host:
            return host, host
    return "model", ""                       # a provider we cannot name: "Your model key"


def provider_words(text: str) -> str:
    """The provider's name (OpenRouter) when ``text`` names one we know, else ""."""
    low = text.lower()
    return next((name for word, _, name in PROVIDERS if word in low), "")


def _cause(text: str, status: str | None) -> str:
    low = text.lower()
    if "expired" in low:
        return "expired"
    if _SQUEEZE.search(text):
        return LOW_CREDIT
    if status == "402" or "credit" in low or "insufficient" in low or "balance" in low:
        return "out of credit"
    if "no api key" in low:
        return "missing"
    if "invalid" in low or "incorrect" in low:
        return "invalid"
    return "refused"


def classify(error: str | None) -> dict[str, str] | None:
    """``{"provider", "name", "cause"}`` when ``error`` is a model key refused, else None.
    ``provider`` is ``"?"`` for a cub's error that names only ``FatalLLMError``."""
    if not error:
        return None
    text = str(error)
    m = _HTTP.search(text)
    missing = _MISSING.search(text)
    words = _KEY_WORDS.search(text)
    if missing:
        env = missing.group(1).lower()
        pid, name = _provider(env.replace("_api_key", "").replace("_", " "))
        return {"provider": pid, "name": name, "cause": "missing"}
    if m:
        status = m.group(1)
        pid, name = _provider(text)
        # a 403 is a key refused only from a provider we know or with the words for it: a
        # source's site may answer 403 too
        if status == "403" and pid not in {p for _, p, _ in PROVIDERS} and not words:
            return None
        return {"provider": pid, "name": name, "cause": _cause(text, status)}
    if words and ("FatalLLMError" in text or "from http" in text or "model" in text.lower()):
        pid, name = _provider(text)
        return {"provider": pid, "name": name, "cause": _cause(text, None)}
    if _SQUEEZE.search(text):                # retried and gave up: still low credit
        pid, name = _provider(text)
        return {"provider": pid, "name": name, "cause": LOW_CREDIT}
    if _CLASS_ONLY.search(text):
        return {"provider": "?", "name": "", "cause": "refused"}
    return None


# the kinds an incident names, in the owner's words (a kind not here: its scheduled form)
NOUNS = {
    "ingest": "reading your sources", "ideas": "idea cards",
    "news.brief": "the topics' briefs", "news.write": "briefs",
    "ideas.card": "cards on a theme", "scout": "scouting", "explain": "explanations",
}


def noun(kind: str, scheduled: str) -> str:
    return NOUNS.get(kind) or (scheduled[:1].lower() + scheduled[1:])


def join(words: list[str]) -> str:
    words = list(dict.fromkeys(w for w in words if w))
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def sentence(name: str, cause: str, when: str, nouns: list[str]) -> str:
    """"Your OpenRouter key was refused (expired) at 08:15 on 25 Oct. Stopped until it is renewed
    in Settings › Watching: reading your sources, idea cards and the newsletter." (a list after
    the colon reads right for one kind or many)"""
    what = join(nouns) or "every model call"
    key = f"Your {name} key" if name else "Your model key"
    who = name or "The model's provider"
    if cause == "missing":
        return f"{key} is missing (since {when}). Stopped until it is set in {KEY_PLACE}: {what}."
    if cause == LOW_CREDIT:
        return (f"{who} asked Kranto to wait at {when}: too little credit for the calls in "
                f"flight. The key works; {what} try again on their next run, and this goes "
                "when a call works.")
    if cause == "out of credit":
        return (f"{key} ran out of credit at {when}. Stopped until credit is added (the key "
                f"test in {KEY_PLACE} says when it works): {what}.")
    return (f"{key} was refused ({cause}) at {when}. Stopped until it is renewed in "
            f"{KEY_PLACE}: {what}.")


def title(name: str, cause: str) -> str:
    key = f"Your {name} key" if name else "Your model key"
    if cause == LOW_CREDIT:
        return f"{name or 'Your model provider'} credit is low: calls wait and try again"
    if cause == "out of credit":
        return f"{key} is out of credit"
    return f"{key} is missing" if cause == "missing" else f"{key} is refused ({cause})"


def blocking(cause: str) -> bool:
    """Whether the incident stops work until the owner acts (low credit retries by itself)."""
    return cause != LOW_CREDIT


def clears(name: str, cause: str) -> str:
    """What makes it go, in words (the incident read tool and the row's help)."""
    who = name or "the same provider"
    if cause == LOW_CREDIT:
        return (f"It goes by itself when a call to {who} works (the next run), or when you "
                "dismiss it.")
    fix = "set the key" if cause == "missing" else \
        "add credit" if cause == "out of credit" else "renew the key"
    return (f"It goes when a later call to {who} works or the key test in {KEY_PLACE} passes "
            f"({fix} first), or when you dismiss it.")


# a provider's incident id → the names its calls are kept under in ``llm_calls.provider``
# (an OpenAI-style endpoint is ``openai_compat`` when it is not OpenRouter by name)
CALL_PROVIDERS = {"openrouter": ("openrouter", "openai_compat"), "anthropic": ("anthropic",),
                  "xai": ("xai",), "claude_code": ("claude_code",)}


def call_providers(provider: str) -> tuple[str, ...]:
    return CALL_PROVIDERS.get(provider, ("openai_compat",) if provider not in ("?", "model")
                              else ())


def short(incident: dict[str, Any]) -> str:
    """The top bar's words: "OpenRouter key refused · reading stopped"."""
    name = incident.get("name") or "Model"
    if incident.get("short"):
        return str(incident["short"])
    if incident.get("cause") == LOW_CREDIT:
        return f"{name} credit low · calls try again"
    first = (incident.get("kinds") or [{}])[0].get("noun") or "model calls"
    return f"{name} key refused · {first} stopped"


# -- which incidents raise the band (the owner, 2026-10-28) ---------------------------------
# "That level of alert should be limited to issues in Kranto itself." The band above the home, the
# top bar's red and ``kranto status``'s INCIDENT lines are for what stops Kranto's own work: a
# refused
# model key (``auth:<provider>``) and Kranto's core (``core:<what>``: the service, the scheduler,
# the database). No feature or cub raises it: their incidents are one Needs you row each, with
# the press that fixes it. Decided here from the class, which the
# activity read sets, never from a flag an incident carries.
BAND_CLASSES = ("auth:", "core:")


def band(incident: dict[str, Any]) -> bool:
    """Whether ``incident`` raises the band (Kranto's own), else it is a Needs you row only."""
    return str(incident.get("class") or incident.get("id") or "").startswith(BAND_CLASSES)
