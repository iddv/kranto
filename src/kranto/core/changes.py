"""What a prepared press will change, in plain words (Needs you's row and the Save dialog).

An assistant's press that waits for the owner (``core.verbs``, Ask me in the UI) is stored with
its verb and fields. Before the owner approves it, the page says, in one sentence, what will
change ("Change your voice card and set Salt to salty") and its dialog lists **every** field the
press will change with its new value, a nested one (``switches``, ``disclosure``) a line per
entry, so nothing bundled into one press is left unsaid (a voice card prepared with Salt showed
the voice card only). Never a field's API name in brackets, never the verb's documentation.

``changes(kind, fields)`` → ``[{"label", "value", "long"}]``; ``summary(kind, title, fields,
subject)`` → one sentence. Pure: no store, no network; a value of any shape is said, never
assumed (a stray number, a null, a list of odd things).
"""

from __future__ import annotations

from typing import Any

SITES = {"blog": "your blog", "newsletter": "your newsletter", "mastodon": "Mastodon",
         "bluesky": "Bluesky", "linkedin": "LinkedIn", "threads": "Threads", "x": "X",
         "substack": "Substack"}
SWITCHES = {"length": "Length", "register": "How formal", "opinions": "Opinions",
            "emoji": "Emoji", "hashtags": "Hashtags", "links": "Links",
            "grade": "Reading level", "salt": "Salt", "salt_thin": "One step saltier on a "
            "post with few facts"}
ROLES = {"judge": "Judge", "reason": "Reasoner"}
SPEND = {"monthly_usd": "watching's monthly cap", "deep_dive_daily_usd": "the deep dives' "
         "daily cap", "x_monthly_usd": "the X cap", "search_monthly_usd": "the live search cap"}
# a field's label wherever the verb does not say its own
LABELS = {
    "voice": "Voice card", "strictness": "The checker", "rules_off": "Rules the checker skips",
    "take": "Ask “What do you think?” on Write a post", "never_add": "Add to the never-list",
    "never_remove": "Take off the never-list", "keep_add": "Add to the keep-list",
    "keep_remove": "Take off the keep-list", "always_add": "Lines every post keeps: add",
    "always_remove": "Lines every post keeps: take off", "samples_add": "Samples to add",
    "samples_remove": "Samples to remove", "role": "Role", "model": "Model",
    "gate": "The Judge's signal threshold", "every_hours": "Read every (hours)",
    "deep_dive_enabled": "Deep dives", "channel": "Update line", "auto": "Update by itself",
    "quiet_window": "When an update may run", "additions": "Your additions",
    "template": "The prompt's template", "note": "Note", "version": "Version",
    "proposal": "Proposal", "answer": "Answer", "markdown": "Markdown", "body": "Words",
    "title": "Title", "parts": "Words",
}
LONG = 120
ORDER = ("voice", "switches", "strictness", "rules_off", "guides", "disclosure", "take",
         "never_add", "never_remove", "keep_add", "keep_remove", "always_add", "always_remove",
         "samples_add", "samples_remove", "role", "model", "gate", "key", "value", "channel",
         "auto", "quiet_window", "title", "body", "parts", "markdown", "additions", "template")


def _site(s: Any) -> str:
    return SITES.get(str(s), str(s))


def _text(v: Any) -> str:
    """Any value as words: a list joined, a bool on or off, a null "none"."""
    if v is None:
        return "none"
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, (list, tuple)):
        if v and all(isinstance(x, dict) and isinstance(x.get("text"), str) for x in v):
            return "\n\n".join(str(x["text"]) for x in v)
        return ", ".join(_text(x) for x in v) or "none"
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_text(x)}" for k, x in v.items()) or "none"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _row(label: str, value: Any) -> dict[str, Any]:
    t = _text(value)
    return {"label": label, "value": t, "long": len(t) > LONG or "\n" in t}


def _usd(v: Any) -> str:
    if v is None:
        return "no cap"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"${f:,.0f}" if f.is_integer() else f"${f:,.2f}"


def changes(kind: str, fields: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every field the press will change, with its new value: ``[{label, value, long}]``.
    A nested field (``switches``, ``disclosure``, ``guides``, ``memory``) is a line per entry."""
    f = fields if isinstance(fields, dict) else {}
    out: list[dict[str, Any]] = []
    # in the order a person reads them (a stored press's fields come back sorted by name)
    for name, v in sorted(f.items(), key=lambda kv: (ORDER.index(kv[0]) if kv[0] in ORDER
                                                     else len(ORDER), kv[0])):
        if v is None and not (kind == "settings.spend" and name in SPEND):
            continue                            # a field not sent changes nothing
        if name == "switches" and isinstance(v, dict):
            for k, x in v.items():
                out.append(_row(SWITCHES.get(str(k), str(k).replace("_", " ").capitalize()), x))
        elif name == "disclosure" and isinstance(v, dict):
            for site, line in v.items():
                out.append(_row(f"Disclosure line on {_site(site)}",
                                line if line not in ("", None) else "off"))
        elif name == "guides" and isinstance(v, dict):
            for site, names in v.items():
                out.append(_row(f"Guides for {_site(site)}",
                                names if names is not None else "Kranto's default"))
        elif name == "samples_add" and isinstance(v, list):
            for i, s in enumerate(v, 1):
                if isinstance(s, dict):
                    where = f" ({_site(s.get('site'))})" if s.get("site") else ""
                    out.append(_row(f"Sample {i} to add{where}", s.get("text")))
                else:
                    out.append(_row(f"Sample {i} to add", s))
        elif kind == "settings.spend" and name in SPEND:
            out.append({"label": SPEND[name][0].upper() + SPEND[name][1:], "value": _usd(v),
                        "long": False})
        elif kind == "settings.models" and name == "role":
            out.append(_row("Role", ROLES.get(str(v), str(v))))
        elif kind == "settings.models" and name == "gate":
            out.append(_row(LABELS["gate"], v))
        elif kind == "update.settings" and name == "auto":
            out.append(_row(LABELS["auto"], "when idle" if v == "idle" else "no, only when you "
                                                                           "choose"))
        elif name == "take" and isinstance(v, bool):
            out.append(_row(LABELS["take"], "yes" if v else "no"))
        else:
            out.append(_row(LABELS.get(name, name.replace("_", " ").capitalize()), v))
    return out


def _quote(v: Any, n: int = 60) -> str:
    t = " ".join(_text(v).split())
    return f"“{t[:n - 1]}…”" if len(t) > n else f"“{t}”"


def _list(v: Any) -> str:
    items = v if isinstance(v, list) else [v]
    return ", ".join(_quote(x, 40) for x in items[:4]) + (" and more" if len(items) > 4 else "")


def _voice(f: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    if f.get("voice") is not None:
        parts.append("change your voice card")
    sw = f.get("switches")
    if isinstance(sw, dict):
        for k, x in sw.items():
            parts.append(f"set {SWITCHES.get(str(k), str(k))} to {_text(x)}")
    if f.get("strictness") is not None:
        s = f["strictness"]
        parts.append("turn the checker off" if s == "off" else f"set the checker to {_text(s)}")
    if f.get("rules_off") is not None:
        parts.append("change which rules the checker skips")
    if isinstance(f.get("take"), bool):
        parts.append("ask “What do you think?” on Write a post" if f["take"]
                     else "stop asking “What do you think?” on Write a post")
    for key, words in (("never_add", "add {} to the never-list"),
                       ("never_remove", "take {} off the never-list"),
                       ("keep_add", "add {} to the keep-list"),
                       ("keep_remove", "take {} off the keep-list"),
                       ("always_add", "add {} to the lines every post keeps"),
                       ("always_remove", "take {} off the lines every post keeps")):
        if f.get(key):
            parts.append(words.format(_list(f[key])))
    d = f.get("disclosure")
    if isinstance(d, dict):
        for site, line in d.items():
            parts.append(f"turn off the disclosure line on {_site(site)}" if line in ("", None)
                         else f"set the disclosure line on {_site(site)}")
    g = f.get("guides")
    if isinstance(g, dict):
        parts.append("change the guides for " + ", ".join(_site(s) for s in g))
    n = len(f["samples_add"]) if isinstance(f.get("samples_add"), list) else 0
    if n:
        parts.append(f"add {n} sample{'s' if n != 1 else ''} of your writing")
    m = len(f["samples_remove"]) if isinstance(f.get("samples_remove"), list) else 0
    if m:
        parts.append(f"remove {m} sample{'s' if m != 1 else ''}")
    return parts


def _join(parts: list[str]) -> str:
    if not parts:
        return ""
    s = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return s[:1].upper() + s[1:]


def summary(kind: str, title: str, fields: dict[str, Any] | None,
            subject: str | None = None) -> str:
    """One plain sentence for what the press will do, without field names or API words."""
    f = fields if isinstance(fields, dict) else {}
    parts: list[str] = []
    if kind == "prose.voice":
        parts = _voice(f)
    elif kind == "settings.models":
        role = ROLES.get(str(f.get("role")), str(f.get("role") or "a role"))
        if f.get("model"):
            parts.append(f"use {f['model']} for the {role} (a model choice changes what Kranto "
                         "spends)")
        if f.get("gate") is not None:
            parts.append(f"set the Judge's signal threshold to {_text(f['gate'])}")
    elif kind == "settings.spend":
        parts = [f"set {SPEND[k]} to {_usd(f[k])}" for k in SPEND if k in f]
    elif kind == "settings.reading":
        if f.get("every_hours") is not None:
            parts.append(f"read every {_text(f['every_hours'])} hours")
        if isinstance(f.get("deep_dive_enabled"), bool):
            parts.append("turn deep dives " + ("on" if f["deep_dive_enabled"] else "off"))
    elif kind == "update.settings":
        if f.get("channel"):
            parts.append(f"follow the {f['channel']} update line")
        if f.get("auto"):
            parts.append("update by itself when idle" if f["auto"] == "idle"
                         else "update only when you choose")
        if f.get("quiet_window"):
            parts.append(f"let an update run only {f['quiet_window']}")
    elif kind in ("prompt.save", "prompt.reset", "prompt.restore"):
        name = f"the {subject} prompt" if subject else "a prompt"
        if kind == "prompt.reset":
            parts.append(f"put {name} back to Kranto's own")
        elif kind == "prompt.restore":
            parts.append(f"bring back version {_text(f.get('version'))} of {name}")
        else:
            what = [w for k, w in (("additions", "your additions"), ("template", "its template"))
                    if f.get(k) is not None]
            parts.append(f"change {' and '.join(what) or 'the words'} of {name}")
    elif kind == "prose.learn" and f.get("answer"):
        parts.append(("say yes to" if f["answer"] == "yes" else "say no to")
                     + " a rule Kranto learned from your edits")
    elif kind in ("cubs.settings", "feature.setting") and f.get("key"):
        where = f" for {subject}" if subject and kind == "feature.setting" else ""
        parts.append(f"set {f['key']}{where} to {_text(f.get('value'))}")
    elif kind == "settings.telemetry" and f.get("mode"):
        parts.append("turn usage reports off" if f["mode"] == "off"
                     else f"send usage reports ({f['mode']}): your consent")
    elif kind.endswith(".draft_markdown") and f.get("markdown"):
        first = str(f["markdown"]).strip().splitlines()[0].lstrip("# ").strip()
        parts.append(f"keep {_quote(first)} as a draft on Post (nothing is sent)")
    if parts:
        return _join(parts) + "."
    rows = changes(kind, f)
    short = [f"{r['label']}: {r['value']}" for r in rows if not r["long"]][:3]
    head = f"{title}" + (f": {subject}" if subject else "")
    return head + (f" ({'; '.join(short)})" if short else "") + "."


__all__ = ["changes", "summary"]
