"""``cub.yaml``'s JSON Schema (``cub.schema.json`` beside this file) and the small
interpreter both sides use: Kranto's validator (``kranto.core.manifest.validate``) runs it before
its own rules, and the SDK's ``FakeHost`` and ``python -m bears_cub.check`` run it on a cub's
folder. Every object is closed (a key the schema does not know is refused), and every key the
schema gives a default is filled before anything else reads the manifest ("defaults first").

The interpreter covers the subset the schema uses: ``type``, ``const``, ``enum``, ``pattern``,
``minLength``/``maxLength``, ``minimum``/``maximum``, ``minItems``/``maxItems``,
``uniqueItems``, ``items``, ``properties``, ``patternProperties``, ``additionalProperties``,
``maxProperties``, ``required``, ``default`` and ``$ref`` into ``$defs``. Standard library only.
"""

from __future__ import annotations

import copy
import functools
import json
import re
from pathlib import Path

SCHEMA_FILE = Path(__file__).with_name("cub.schema.json")
# the manifest key that names the host versions a cub was tested with (">=0.5,<0.7")
HOST_RANGE = "bears"


class ManifestError(ValueError):
    """A manifest Kranto refuses, with where and why."""


@functools.cache
def _raw() -> str:
    return SCHEMA_FILE.read_text(encoding="utf-8")


def load() -> dict:
    """The schema as shipped (a fresh copy: a caller may widen it)."""
    return json.loads(_raw())


_TYPE_WORDS = {"object": "a mapping", "array": "a list", "string": "text",
               "integer": "a whole number", "number": "a number", "boolean": "true or false",
               "null": "null"}


def _is(v, t: str) -> bool:
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, int | float) and not isinstance(v, bool)
    if t == "boolean":
        return isinstance(v, bool)
    return v is None


def pattern_ok(pattern: str, v: str) -> bool:
    """A JSON Schema ``pattern``: anchored ones match the whole string (Python's ``$`` would
    let a trailing newline through)."""
    if pattern.startswith("^") and pattern.endswith("$"):
        return re.fullmatch(pattern[1:-1], v) is not None
    return re.search(pattern, v) is not None


def _name(path: list) -> str:
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out or "the manifest"


def _deref(s: dict, root: dict) -> dict:
    if "$ref" in s:
        return root["$defs"][s["$ref"].rsplit("/", 1)[1]]
    return s


def walk(v, s: dict, path: list, root: dict):
    """Check ``v`` against schema ``s`` and fill the defaults of absent properties; returns
    ``v`` (objects are filled in place). Raises ``ManifestError`` naming the key."""
    s = _deref(s, root)
    where = _name(path)
    types = s.get("type")
    if types is not None:
        types = types if isinstance(types, list) else [types]
        if not any(_is(v, t) for t in types):
            raise ManifestError(f"{where} must be {' or '.join(_TYPE_WORDS[t] for t in types)}")
    if "const" in s and v != s["const"]:
        raise ManifestError(f"{where} must be {s['const']!r}")
    if "enum" in s and v not in s["enum"]:
        raise ManifestError(f"{where} is one of {', '.join(map(str, s['enum']))}")
    if isinstance(v, str):
        if len(v) < s.get("minLength", 0):
            raise ManifestError(f"{where} is empty")
        if "maxLength" in s and len(v) > s["maxLength"]:
            raise ManifestError(f"{where} is at most {s['maxLength']} characters")
        if "pattern" in s and not pattern_ok(s["pattern"], v):
            raise ManifestError(f"{where}: {v[:80]!r} is not of the expected shape")
    if _is(v, "number"):
        if "minimum" in s and v < s["minimum"]:
            raise ManifestError(f"{where} is at least {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            raise ManifestError(f"{where} is at most {s['maximum']}")
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0):
            raise ManifestError(f"{where} needs at least {s['minItems']}")
        if "maxItems" in s and len(v) > s["maxItems"]:
            raise ManifestError(f"{where} holds at most {s['maxItems']}")
        if s.get("uniqueItems"):
            seen = [json.dumps(x, sort_keys=True) for x in v]
            if len(set(seen)) != len(seen):
                raise ManifestError(f"{where} names something twice")
        if "items" in s:
            for i, x in enumerate(v):
                walk(x, s["items"], [*path, i], root)
    if isinstance(v, dict):
        _walk_object(v, s, path, root, where)
    return v


def _walk_object(v: dict, s: dict, path: list, root: dict, where: str) -> None:
    props = s.get("properties", {})
    pats = s.get("patternProperties", {})
    extra = s.get("additionalProperties", True)

    def matching(k) -> list[dict]:
        return [sub for rx, sub in pats.items() if pattern_ok(rx, str(k))]

    unknown = [str(k) for k in v if k not in props and not matching(k) and extra is False]
    if unknown:
        raise ManifestError(f"unknown keys in {where}: {', '.join(sorted(unknown))}")
    if "maxProperties" in s and len(v) > s["maxProperties"]:
        raise ManifestError(f"{where} holds at most {s['maxProperties']} keys")
    for k in s.get("required", []):
        if k not in v:
            raise ManifestError(f"{where} needs {k}")
    for k, sub in props.items():
        target = _deref(sub, root)
        if k not in v and "default" in target:
            v[k] = copy.deepcopy(target["default"])
    for k in list(v):
        if k in props:
            walk(v[k], props[k], [*path, k], root)
            continue
        subs = matching(k)
        for sub in subs:
            walk(v[k], sub, [*path, k], root)
        if not subs and isinstance(extra, dict):
            walk(v[k], extra, [*path, k], root)


def check(m: dict, schema: dict | None = None) -> dict:
    """``m`` checked against the schema (as shipped unless one is given), defaults filled in
    place; returns it."""
    if not isinstance(m, dict):
        raise ManifestError("a manifest is a mapping of keys")
    root = schema if schema is not None else load()
    return walk(m, root, [], root)


GRANT_BLOCKS = ("reads", "events", "model", "search", "http", "broker", "requests", "storage")


def grants_of(m: dict) -> dict:
    """The grant blocks of a checked manifest (defaults filled), as Kranto stores them when the
    owner approves an install and sends them in ``hello.granted``: reads (and
    ``reads_topics``, the topics a narrowed cub sees, null for all), events, model, search,
    http, broker, requests, storage, and the ids of its build stages."""
    out = {k: json.loads(json.dumps(m.get(k))) for k in GRANT_BLOCKS if k in m}
    out.setdefault("reads", [])
    ev = m.get("events") or {}
    out["events"] = {"publish": list(ev.get("publish", [])),
                     "subscribe": [dict(s) for s in ev.get("subscribe", [])]}
    out.setdefault("model", {"tiers": [], "purposes": [], "monthly_usd": None})
    out.setdefault("search", [])
    out.setdefault("http", {"hosts": []})
    out.setdefault("broker", {})
    out.setdefault("requests", [])
    out.setdefault("storage", "own")
    out["reads_topics"] = None
    out["stages"] = [s["id"] for s in m.get("stages", [])]
    return out


def manifest_hash(manifest: dict) -> str:
    """The pin: sha256 of the manifest's canonical JSON, taken over ``cub.yaml`` as loaded,
    before any default is filled. Kranto computes the same (``kranto.core.manifest``)."""
    import hashlib
    text = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def load_file(path: str | Path) -> dict:
    """A ``cub.yaml`` read as data (at most 64 KiB, a mapping). Needs PyYAML, which the SDK
    depends on and Kranto binds beside the SDK in a cub's sandbox."""
    import yaml

    p = Path(path)
    raw = p.read_bytes()
    if len(raw) > 64 * 1024:
        raise ManifestError(f"{p.name} is over 64 KiB")
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ManifestError(f"{p.name} is not YAML: {str(exc).splitlines()[0]}") from None
    if not isinstance(data, dict):
        raise ManifestError(f"{p.name} is not a mapping of keys")
    return data
