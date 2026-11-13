"""What ``loop.yaml`` may hold, checked against ``DEFAULTS`` (S-6b; review D-4).

``check(data)`` returns problems, each ``{"kind", "key", "detail"}``:

- ``unknown``: a key Kranto does not read (a typo, or a key from a newer or older version).
  Never an error: the file keeps it, Kranto ignores it as before, ``Config.problems`` lists it
  and the loop says so once (``brb loop status``, the loop's log). An unknown key must never
  stop Kranto from starting.
- ``type``: a key kranto reads, with a value of the wrong kind (``build.stage_caps: "lots"``).
  A build refuses to start while one sits under ``build.models``, ``build.stage_caps``,
  ``build.max_usd`` or ``daily_usd`` (``refuses_builds``): running it without the owner's caps
  or models is the silent failure the review found (a broken file meant an uncapped build).

The shape is ``DEFAULTS``: a mapping's keys are known; a key whose default is None takes any
value; an empty mapping (``build.models``, ``build.stage_caps``) takes any key; and
``capabilities`` holds, besides its own settings, one entry per capability by name.
"""
from __future__ import annotations

import re

from .store import DEFAULTS

# a model name the CLI or the router accepts (models.py reads it here)
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,119}")


def check_model(model) -> str | None:
    """A model name from a request: a string the CLI or the router accepts, or None (the
    default). Raises ValueError otherwise."""
    if model is None or model == "":
        return None
    if not isinstance(model, str) or not MODEL_NAME.fullmatch(model.strip()):
        raise ValueError("a model is a name such as claude-haiku-5-5, or empty for the "
                         "default")
    return model.strip()


# capabilities.<name>: what writes per capability
CAPABILITY_KEYS = {"enabled", "pin", "scope", "stages", "settings", "traits"}
# a wrong value here means a build would run without the owner's caps or stage models
# spend caps default to null (uncapped): a value there is a number of dollars
USD_CAPS = {"daily_usd", "build.max_usd", "revise.max_usd", "maintain.max_usd",
            "projects.budget.monthly_usd", "term.daily_usd", "ideas.research.max_usd"}
BUILD_CRITICAL = (("build", "models"), ("build", "stage_caps"), ("build", "max_usd"),
                  ("daily_usd",))
# keys an older kranto read and this one retired with what they set (the project chat's, 
# 0.3.71; the gate's p_hidden check, #5): not a typo, so not an unknown key; the file keeps
# them and nothing reads them. A may_override list that still names p_hidden is harmless: no
# check of that name holds a build any more. Publishing's (HC, 0.3.75: wording is never a hold;
# #7 and #8: the pre-push scans always run with the installed Kranto, so the whole gate
# section went; publish.maintenance: false is maintenance_files: none; the test hooks are
# environment variables)
RETIRED = {"chat.model", "chat.timeout_s", "chat.max_turns", "chat.concurrency", "chat.sandbox",
           "chat.auto", "gate", "publish.block_on_jargon", "publish.honesty_repair_rounds",
           "publish.negotiate", "publish.maintenance", "publish.precheck_command",
           "publish.precheck_inline",
           # #8: keys nothing read (a cap that capped nothing among them), and the weekly
           # editor's read budget, beats, memory and timeouts, constants since
           "maintain.reruns", "maintain.adopt.clone_timeout_s",
           "projects.charter.redraft_after_merges", "projects.topic.max_sources",
           "projects.evolve.tools", "projects.evolve.max_usd", "projects.health.quiet_days",
           "ideas.editor.read_budget", "ideas.editor.beats", "ideas.editor.memory_weeks",
           "ideas.editor.timeout_s", "ideas.research.timeout_s"}


def _kind(v) -> str:
    if isinstance(v, bool):
        return "true or false"
    if isinstance(v, (int, float)):
        return "a number"
    if isinstance(v, str):
        return "text"
    if isinstance(v, list):
        return "a list"
    if isinstance(v, dict):
        return "a mapping"
    return type(v).__name__


def _fits(default, value) -> bool:
    if default is None or value is None:
        return True
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, (list, tuple)):
        return isinstance(value, (list, tuple))
    if isinstance(default, dict):
        return isinstance(value, dict)
    return True


def check(data, defaults: dict = DEFAULTS) -> list[dict]:
    """The problems of a parsed ``loop.yaml`` (``{}`` for an empty file)."""
    out: list[dict] = []
    if data is None:
        return out
    if not isinstance(data, dict):
        return [{"kind": "type", "key": "", "detail": "loop.yaml is not a mapping of keys"}]

    def walk(node: dict, spec: dict, path: tuple):
        for k, v in node.items():
            here = (*path, str(k))
            key = ".".join(here)
            if path == ("capabilities",) and k not in spec:
                if not isinstance(v, dict):
                    out.append({"kind": "type", "key": key,
                                "detail": f"a capability's entry is a mapping, not {_kind(v)}"})
                    continue
                for sub in v:
                    if sub not in CAPABILITY_KEYS:
                        out.append({"kind": "unknown", "key": f"{key}.{sub}",
                                    "detail": "not a capability setting kranto reads"})
                continue
            if k not in spec:
                if key not in RETIRED:
                    out.append({"kind": "unknown", "key": key, "detail": "not a key kranto reads"})
                continue
            d = spec[k]
            if key in USD_CAPS and v is not None and (isinstance(v, bool)
                                                     or not isinstance(v, (int, float))):
                out.append({"kind": "type", "key": key,
                            "detail": f"should be a number of dollars or null, is {_kind(v)}"})
                continue
            if not _fits(d, v):
                out.append({"kind": "type", "key": key,
                            "detail": f"should be {_kind(d)}, is {_kind(v)}"})
                continue
            if isinstance(d, dict) and d and isinstance(v, dict):
                walk(v, d, here)

    walk(data, defaults, ())
    return out + inert(data)


# D14: with build.flow: simple, these keys of today's flow do nothing (the
# file is never rewritten; ``kranto doctor`` and the loop's status say so). verify and repair
# map onto check and fix; build.auto_repair is the simple flow's own fix rounds.
INERT_SIMPLE = {"build.auto_repair": "the simple flow's fix rounds are build.fix_rounds",
                **{f"build.models.{k}": "the simple flow has no such step"
                   for k in ("claims", "oracle", "readiness")},
                **{f"build.stage_caps.{k}": "the simple flow has no such step"
                   for k in ("claims", "oracle", "reverify", "readiness")}}
# Track LEAN: with build.flow: lean, the same for the lean flow (verify and readiness map onto
# check, repair onto fix; a held lean build gets no automatic round: it had its one fix).
INERT_LEAN = {"build.auto_repair": "the lean flow's one fix session ran before the gate",
              "build.fix_rounds": "the lean flow has one fix session",
              **{f"build.models.{k}": "the lean flow has no such step"
                 for k in ("plan", "claims", "oracle")},
              **{f"build.stage_caps.{k}": "the lean flow has no such step"
                 for k in ("plan", "claims", "oracle", "reverify")}}
INERT = {"simple": INERT_SIMPLE, "lean": INERT_LEAN}


def inert(data) -> list[dict]:
    """The keys set in ``loop.yaml`` that do nothing with the flow it picks (``build.flow:
    simple`` or ``lean``): ``{"kind": "inert", "key", "detail"}``. Never a reason to refuse
    a build."""
    b = (data or {}).get("build") if isinstance(data, dict) else None
    flow = str(b.get("flow") or "v5") if isinstance(b, dict) else "v5"
    if flow not in INERT:
        return []
    out = []
    for key, why in INERT[flow].items():
        node = data
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None:
            out.append({"kind": "inert", "key": key,
                        "detail": f"does nothing with build.flow: {flow} ({why})"})
    return out


def refuses_builds(problems: list[dict]) -> list[dict]:
    """The problems a build must not start with (``BUILD_CRITICAL``)."""
    crit = {".".join(p) for p in BUILD_CRITICAL}
    return [p for p in problems if p["kind"] == "type"
            and any(p["key"] == c or p["key"].startswith(c + ".") for c in crit)]


def describe(problems: list[dict], limit: int = 5) -> str:
    """One line for a log or a status: ``loop.yaml: 2 unknown keys (a.b, c); 1 wrong value
    (build.stage_caps: should be a mapping, is text)``."""
    unk = [p["key"] for p in problems if p["kind"] == "unknown"]
    bad = [f"{p['key']}: {p['detail']}" for p in problems if p["kind"] == "type"]
    idle = [p["key"] for p in problems if p["kind"] == "inert"]
    parts = []
    if unk:
        parts.append(f"{len(unk)} unknown key{'s' if len(unk) != 1 else ''} (ignored): "
                     + ", ".join(unk[:limit]) + (", ..." if len(unk) > limit else ""))
    if bad:
        parts.append(f"{len(bad)} wrong value{'s' if len(bad) != 1 else ''}: "
                     + "; ".join(bad[:limit]) + ("; ..." if len(bad) > limit else ""))
    if idle:
        flow = next((p["detail"].split("build.flow: ", 1)[1].split(" ", 1)[0]
                     for p in problems if p["kind"] == "inert"), "simple")
        parts.append(f"{len(idle)} key{'s' if len(idle) != 1 else ''} doing nothing with "
                     f"build.flow: {flow}: " + ", ".join(idle[:limit])
                     + (", ..." if len(idle) > limit else ""))
    return "loop.yaml: " + "; ".join(parts) if parts else ""
