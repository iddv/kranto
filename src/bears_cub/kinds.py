"""What ``FakeHost`` enforces as Kranto does: the ticket kinds a
cub may ask for with their typed fields and daily caps, and the broker operations a cub may be
granted with their arguments. A test in Kranto holds these equal to the core's own tables
(``core.tickets.KINDS``, the broker adapters), so a cub that passes against ``FakeHost`` is
refused nothing at runtime for a reason its tests could have caught.

A field: ``(type, {pattern, max_len, choices, lo, hi})`` with type ``str``, ``enum``, ``int``,
``float`` or ``iso``.
"""

from __future__ import annotations

TICKETS: dict[str, dict] = {
    # ``expires_hours`` None: the ask waits until it is answered (Kranto 0.6: a draft waits until
    # it is seen); ``series``: a newer ticket of the kind replaces the open older one
    "send.newsletter": {
        "per_day": 3, "expires_hours": None, "series": True,
        "fields": {"draft_ref": ("str", {"pattern": r"[a-z]{2,8}:[A-Za-z0-9-]{1,64}",
                                         "max_len": 80}),
                   "subject": ("str", {"max_len": 200}),
                   "audience": ("enum", {"choices": ("all",)}),
                   "when": ("str", {"pattern": r"now|[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
                                               r"[0-9]{2}(:[0-9]{2})?Z", "max_len": 20})}},
    "post.mastodon": {
        "per_day": 5, "expires_hours": None,
        "fields": {"draft_ref": ("str", {"pattern": r"draft:[0-9]{1,12}", "max_len": 20}),
                   "text": ("str", {"max_len": 500}),
                   "visibility": ("enum", {"choices": ("public", "unlisted", "private")}),
                   "language": ("str", {"pattern": r"[a-z]{2}(-[A-Za-z]{2})?", "max_len": 5})}},
    "draft.sanity": {
        "per_day": 3, "expires_hours": None,
        "fields": {"draft_ref": ("str", {"pattern": r"draft:[0-9]{1,12}", "max_len": 20}),
                   "title": ("str", {"max_len": 200}),
                   "slug": ("str", {"pattern": r"[a-z0-9]+(-[a-z0-9]+)*", "max_len": 96}),
                   "category": ("enum", {"choices": ("dispatch", "build")})}},
    "book.propose": {
        "per_day": 3, "expires_hours": 24,
        "fields": {"legs": ("str", {"max_len": 400}),
                   "total": ("float", {"lo": 0, "hi": 1000000}),
                   "currency": ("enum", {"choices": ("EUR", "USD", "GBP")}),
                   "links": ("str", {"max_len": 400})}},
}

# Broker operations a cub may be granted: side (read or draft), whether a credential is
# needed, the windows, and the arguments (each ``(type, rules, required)``). ``newsletter`` is
# whichever newsletter platform the owner connects: a cub never names one.
BROKER: dict[str, dict[str, dict]] = {
    "newsletter": {
        "emails.create_draft": {
            "side": "draft", "needs_credential": False, "per_day": 20,
            "args": {"subject": ("str", {"max_len": 200}, True),
                     "body": ("str", {"max_len": 200000}, True)}},
        "emails.get": {"side": "read", "needs_credential": False, "per_hour": 60,
                       "args": {"draft_ref": ("str", {"max_len": 80}, True)}},
        "drafts.list": {"side": "read", "needs_credential": False, "per_hour": 60,
                        "args": {"limit": ("int", {"lo": 1, "hi": 50}, False)}},
        "newsletter.get": {"side": "read", "needs_credential": True, "per_hour": 60,
                           "args": {}},
    },
    "mastodon": {
        "statuses.draft": {
            "side": "draft", "needs_credential": False, "per_day": 20,
            "args": {"text": ("str", {"max_len": 5000}, True),
                     "visibility": ("enum", {"choices": ("public", "unlisted", "private")},
                                    False),
                     "language": ("str", {"pattern": r"[a-z]{2}(-[A-Za-z]{2})?",
                                          "max_len": 5}, False),
                     "spoiler_text": ("str", {"max_len": 200}, False)}},
        "drafts.list": {"side": "read", "needs_credential": False, "per_hour": 60,
                        "args": {"limit": ("int", {"lo": 1, "hi": 50}, False)}},
        "account.get": {"side": "read", "needs_credential": True, "per_hour": 60, "args": {}},
        "instance.limits": {"side": "read", "needs_credential": True, "per_hour": 60,
                            "args": {}},
    },
    # A post filed as a draft in the owner's Sanity dataset, never published by Kranto.
    "sanity": {
        "documents.draft": {
            "side": "draft", "needs_credential": False, "per_day": 20,
            "args": {"doc": ("str", {"pattern": r"[a-z0-9]+(-[a-z0-9]+)*", "max_len": 80}, True),
                     "title": ("str", {"max_len": 200}, True),
                     "slug": ("str", {"pattern": r"[a-z0-9]+(-[a-z0-9]+)*", "max_len": 96},
                              True),
                     "body": ("str", {"max_len": 200000}, True),
                     "category": ("enum", {"choices": ("dispatch", "build")}, True),
                     "excerpt": ("str", {"max_len": 280}, False),
                     "tags": ("str", {"max_len": 600}, False),
                     "email_teaser": ("str", {"max_len": 1200}, False),
                     "x_post": ("str", {"max_len": 280}, False),
                     "linkedin_post": ("str", {"max_len": 1300}, False),
                     "origin": ("enum", {"choices": ("brief", "topic", "build", "markdown",
                                                     "pick", "radar", "card")}, False),
                     "cites": ("str", {"max_len": 400}, False)}},
        "documents.get": {"side": "read", "needs_credential": True, "per_hour": 60,
                          "args": {"draft_ref": ("str", {"max_len": 20}, True)}},
        "drafts.list": {"side": "read", "needs_credential": False, "per_hour": 60,
                        "args": {"limit": ("int", {"lo": 1, "hi": 50}, False)}},
    },
}

# The v1 read families and the read names a cub may ask for (protocol).
READ_FAMILIES = ("topics", "library", "themes", "ideas", "briefs", "events", "objects", "spend")
READS = ("topics.list", "library.observations", "library.search", "themes.list", "themes.get",
         "ideas.list", "ideas.get", "briefs.list", "briefs.get", "objects.get", "events.read",
         "spend.mine", "grades.mine", "cards.get")


def refused_grant(m: dict) -> str | None:
    """Why Kranto would refuse a checked manifest's ``requests`` or ``broker`` at install, or
    None: a kind a cub may not ask for (``trade.instruct`` is Kranto's own), a service or an
    operation Kranto does not offer a cub (a perform operation never is)."""
    bad = [k for k in m.get("requests") or [] if k not in TICKETS]
    if bad:
        return (f"requests: {', '.join(bad)} is not an action a cub may ask for (it may ask "
                f"for {', '.join(sorted(TICKETS))})")
    for service, ops in (m.get("broker") or {}).items():
        offered = BROKER.get(service)
        if offered is None:
            return f"broker: no {service} operations a cub may be granted"
        wrong = [o for o in ops if o not in offered]
        if wrong:
            return f"broker.{service}: no such operation a cub may be granted: {', '.join(wrong)}"
    return None


def check_value(where: str, value, ftype: str, rules: dict) -> str | None:
    """Why ``value`` does not fit its field, or None."""
    import re
    from datetime import datetime

    if ftype == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{where} must be a whole number"
    elif ftype == "float":
        if isinstance(value, bool) or not isinstance(value, int | float):
            return f"{where} must be a number"
    elif ftype in ("str", "iso"):
        if not isinstance(value, str) or not value or len(value) > rules.get("max_len", 120):
            return f"{where} must be text of 1 to {rules.get('max_len', 120)} characters"
        if ftype == "iso":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return f"{where} must be an ISO time"
    elif ftype == "enum" and value not in rules.get("choices", ()):
        return f"{where} must be one of {', '.join(map(str, rules.get('choices', ())))}"
    if rules.get("pattern") and not re.fullmatch(rules["pattern"], str(value)):
        return f"{where}: {value!r} is not of the expected shape"
    lo, hi = rules.get("lo"), rules.get("hi")
    if ftype in ("int", "float") and (lo is not None and value < lo
                                      or hi is not None and value > hi):
        return f"{where} must be between {lo} and {hi}"
    return None
