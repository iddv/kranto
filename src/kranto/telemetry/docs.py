"""The public field page, ``docs/privacy/what-kranto-sends.md``, made from the allow-list
(``kranto telemetry docs``; a test fails when the page in the repository is not this text).

It is made from the server's own part of the list, so it reads the same with or without
the page installed; the keys whose names come from the page (one per action, per page, per
build check and stage) say where their list is."""

from __future__ import annotations

from . import schema as schema_mod
from .local import DEFAULT_ENDPOINT

FROM_PAGE = {
    "action": "one per action Kranto has (the buttons and commands: "
    "`src/kranto/page/telemetry.json`, `action`)",
    "origin": "ui, mcp, cli, auto, honesty, agent",
    "node": "one per page of the app (`src/kranto/page/telemetry.json`, `node`)",
    "check": "the release gate's checks (`src/kranto/page/telemetry.json`, `check`)",
    "stage": "the build stages (`src/kranto/page/telemetry.json`, `stage`)",
    "build_outcome": "started, ready, held, failed, published_private, published_public, "
    "stopped, cancelled",
    "intake_mode": "manual, rule, editor",
}

NEVER = (
    "topic names and descriptions",
    "source URLs and names",
    "card, observation and idea text",
    "repo names and owners",
    "product names",
    "code",
    "prompts and model replies",
    "chat or terminal content",
    "the words of a grade",
    "tokens, keys and the .env",
    "emails and user names",
    "host names and file paths",
    "IP addresses (the receiving "
    "server reads the address only to derive a country code and discards it)",
    "the time zone, the locale, the screen size",
    "version strings of the kernel or distribution",
    "your GitHub login",
    "anything in data/secrets",
)


def notice() -> str:
    """The privacy notice (``notice.md``), with the controller and the contact the owner
    gave."""
    from importlib import resources

    return resources.files(__package__).joinpath("notice.md").read_text()


def _type(spec: dict, schema: dict) -> str:
    kind = spec.get("type")
    if kind == "int":
        return f"whole number {spec.get('min', 0)} to {spec.get('max')}"
    if kind == "bool":
        return "true or false"
    if kind == "str" and "enum" in spec:
        name = spec["enum"]
        values = schema["enums"].get(name)
        return "one of: " + (", ".join(values) if values else FROM_PAGE.get(name, name))
    if kind == "str":
        return f"text matching the pattern `{spec['pattern']}`"
    if kind == "template":
        return (
            f"text of at most {spec.get('max_len', 200)} characters: only the words listed "
            "below, `<x>`, `<n>` and punctuation"
        )
    return kind or "?"


def _key(key: str, schema: dict) -> str:
    out = key
    for name in schema_mod._PLACEHOLDER.findall(key):
        out = out.replace("{" + name + "}", f"<{name}>")
    return f"`{out}`"


EVENT_WORDS = {
    "verb": (
        "`kranto.verb`: a verb's calls in one hour",
        "One record per hour, verb, door, assistant, outcome, refusal kind and rung, counted "
        "by Kranto itself at the verbs' door (so Codex and any client without hooks are "
        "covered), and for the page's own clicks by their route.",
    ),
    "session": (
        "`kranto.session`: one assistant session",
        "One record per session that ended (or went idle for 12 hours), from Kranto's "
        "plugin hooks in Claude Code and Codex. The session's id pairs its start with "
        "its end on your machine, as a hash, and is never sent.",
    ),
    "command": (
        "`kranto.command`: a slash command's uses in one hour",
        "One record per hour, Kranto slash command and assistant. Only a prompt that "
        "starts with `/kranto:` is looked at, and only the command's name is kept.",
    ),
}


def example_envelope(kind: str, schema: dict) -> dict:
    """One record of ``kind`` as it would be posted, made from the list's examples and a
    fixed hour (2026-10-28 08:00 UTC)."""
    from . import assistant

    res = {k: s["example"] for k, s in schema["resource"].items() if s["tier"] != "relay"}
    res.update(tier="detailed", install_id="8a1f3c52-1111-4222-8333-444455556666")
    rec = {k: s["example"] for k, s in schema["assistant"][kind].items()}
    return assistant.envelope(res, [(kind, rec, 1793174400)])


def _assistant(schema: dict) -> list[str]:
    import json

    lines = [
        "",
        "## The assistant's usage (detailed only)",
        "",
        "With `detailed`, and only then, Kranto also sends how its assistant tools are used, "
        "hour by hour: with `basic`, `local`, `off`, before you answer, or with "
        "`DO_NOT_TRACK=1`, none is kept or sent, and leaving `detailed` deletes any "
        "waiting. The hours that have ended go together, at most 200 records a request and "
        "3 requests an hour (a long session is one request an hour, not one a call), with "
        "the resource above (the install id included) and a time no finer than the hour. "
        "A Kranto tool call that fails or times out in an assistant's session is an error "
        "report (`where: console`, above), which follows the error reports' choice. Read "
        "what waits with `kranto telemetry show --assistant` (`--wire` for the exact bytes) "
        "and every batch sent with `kranto telemetry show --sent`.",
        "",
        "**Your consent is yours.** Choosing `basic` or `detailed` is done by you on "
        "the page (Settings › Privacy & access) or in your own terminal: an assistant "
        "working in Kranto can prepare the choice for your approval (verb "
        "`settings.telemetry`), never make it, under every assistant setting; `kranto "
        "telemetry basic|detailed` is refused inside an assistant's session. Over HTTP only "
        "the page, signed in, can choose them: a token (the command line's, an assistant's) "
        "is refused, and so is everyone when the server's tokens are switched off. An assistant "
        "may turn reports off at once (verb `telemetry.off`). The first time Kranto's "
        "plugin starts in an install that never answered, it shows one line pointing to "
        "`/kranto:telemetry` and this setting, and never again.",
    ]
    for kind, (title, says) in EVENT_WORDS.items():
        lines += [
            "",
            f"### {title}",
            "",
            says,
            "",
            "| Field | Type | Example | Why |",
            "|---|---|---|---|",
        ]
        for k, spec in schema["assistant"][kind].items():
            need = " (always)" if spec.get("required") else ""
            lines.append(
                f"| `{k}`{need} | {_type(spec, schema)} | {spec.get('example')} | "
                f"{spec.get('doc', '')} |"
            )
        lines += [
            "",
            "One, exactly as it would be posted (before gzip):",
            "",
            "```json",
            json.dumps(example_envelope(kind, schema), indent=1, sort_keys=True),
            "```",
        ]
    lines += [
        "",
        "Where the values come from:",
        "",
        "- `<verb>`: one per verb Kranto has (`core/verbs.py`; the build loop's as "
        "`b.<action>`), else other",
        f"- `<surface>`: {', '.join(schema['enums']['surface'])}",
        f"- `<client>`: {', '.join(schema['enums']['client'])}",
        f"- `<refusal>`: {', '.join(schema['enums']['refusal'])}",
        f"- `<command>`: {', '.join(schema['enums']['command'])}",
    ]
    return lines


def page() -> str:
    schema = schema_mod.own()
    lines = [
        "# What Kranto sends",
        "",
        "*Made by `kranto telemetry docs` from the allow-list "
        "(`src/kranto/telemetry/schema.json`, schema "
        f"{schema['schema']}). Do not edit by hand.*",
        "",
        "Kranto counts how it is used on your machine and, only if you choose `basic` or "
        "`detailed`, sends one report a day and an error report within minutes when "
        "something fails. A field that is not on this page cannot be "
        "sent: Kranto drops anything else before it is written, and every report is "
        "checked against this list before it leaves. Nothing is sent before you answer, "
        "or with `local` or `off`. With `basic` or `detailed`, each day's report goes "
        "between 02:00 and 05:00 UTC the next morning, starting with the first whole day "
        "after you chose, to the controller's relay on AWS in the EU "
        f"(`{DEFAULT_ENDPOINT}`), unless `KRANTO_TELEMETRY_ENDPOINT` or "
        "`telemetry.endpoint` names another.",
        "",
        "Read today's report with `kranto telemetry show` and everything sent with "
        "`kranto telemetry show --sent`; stop with `kranto telemetry off`, Settings › "
        "Privacy & access, or `DO_NOT_TRACK=1`.",
        "",
        notice().rstrip("\n"),
        "",
        "## Every report: what kind of install sent it",
        "",
        "| Field | Type | Tier | Example | Why |",
        "|---|---|---|---|---|",
    ]
    for k, spec in schema["resource"].items():
        tier = {"basic": "basic", "detailed": "detailed only", "relay": "added by the server"}[
            spec["tier"]
        ]
        lines.append(
            f"| `{k}` | {_type(spec, schema)} | {tier} | {spec.get('example')} | "
            f"{spec.get('doc', '')} |"
        )
    lines += [
        "",
        "## The daily report (basic and detailed)",
        "",
        "Placeholders in angle brackets stand for one field per value: "
        "`actions.<action>` is `actions.publish`, `actions.retry` and so on.",
        "",
        "| Field | Type | Example | Why |",
        "|---|---|---|---|",
    ]
    for k, spec in schema["daily"].items():
        lines.append(
            f"| {_key(k, schema)} | {_type(spec, schema)} | {spec.get('example')} | "
            f"{spec.get('doc', '')} |"
        )
    lines += ["", "Where the placeholders' values come from:", ""]
    names = sorted({n for k in schema["daily"] for n in schema_mod._PLACEHOLDER.findall(k)})
    for n in names:
        if n in schema["enums"] and schema["enums"][n]:
            lines.append(f"- `<{n}>`: {', '.join(schema['enums'][n])}")
        elif n in schema["patterns"]:
            lines.append(
                f"- `<{n}>`: text matching `{schema['patterns'][n]}` (the exception's "
                "class and up to five lines of Kranto's own code; never its message)"
                if n == "fingerprint"
                else f"- `<{n}>`: `{schema['patterns'][n]}`"
            )
        else:
            lines.append(f"- `<{n}>`: {FROM_PAGE.get(n, n)}")
    lines += [
        "",
        "## Error reports (basic and detailed)",
        "",
        "Error reports follow your choice exactly: with `basic` or `detailed`, when "
        "something fails in Kranto (a request, a scheduled job, one row of a list, the "
        "build loop, an update's self-check) an error report is sent within minutes; "
        "with `local`, `off`, before you answer, or with `DO_NOT_TRACK=1`, none is kept "
        "or sent, and choosing `local` or `off` deletes any waiting. Each report goes with "
        "the fields above (`basic`: no identifier; `detailed`: the install id too) and a "
        "time no finer than the hour. The same error is reported at most once an hour, "
        "with a count of how often it happened; at most 4 batches of at most 10 reports "
        "go in an hour, and at most 50 reports a day. Read the reports waiting with "
        "`kranto telemetry show --errors` (`--wire` for the exact bytes) and every batch "
        "sent with `kranto telemetry show --sent`, or in Settings › Privacy & access.",
        "",
        "| Field | Type | Example | Why |",
        "|---|---|---|---|",
    ]
    for k, spec in schema["error"].items():
        lines.append(
            f"| `{k}` | {_type(spec, schema)} | {spec.get('example')} | {spec.get('doc', '')} |"
        )
    lines += [
        "",
        "Where the values come from:",
        "",
        f"- `<where>`: {', '.join(schema['enums']['where'])}",
        f"- `<job>`: {', '.join(schema['enums']['job'])}",
        "- `<route>`: the route patterns listed under `api.slow.<route>` above",
        "- the words a message may keep (any other word becomes `<x>`, a number `<n>`): "
        + ", ".join(f"`{w}`" for w in schema["enums"]["message_word"]),
    ]
    lines += _assistant(schema)
    lines += ["", "## Never, in any tier", ""]
    lines += [f"- {n}" for n in NEVER]
    lines += [
        "",
        "The list has no field of a type that could carry them: text exists only as "
        "a closed list of values or a fixed pattern.",
        "",
    ]
    return "\n".join(lines)
