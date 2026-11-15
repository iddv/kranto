"""The allow-list (section 1.4): ``schema.json`` here, with the page's enums and lines
laid over it when the page is installed (``kranto.page.host_api.telemetry_schema``).

Two checks use it. ``clean_line`` keeps what a local line may hold: a field the line's spec
does not name, or a value of the wrong type, out of range, outside its enum or not matching its
pattern, is dropped and counted (never redacted: a marker would show something was there).
``check_report`` is strict: the daily report, the resource and every key in them must be in the
list, or the report is refused with the first reason; nothing that fails it is ever sent.

A key such as ``actions.{action}`` stands for one key per value of the ``action`` enum (or
match of a pattern of that name), so ``actions.publish`` is allowed and ``actions.anything``
is not."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources

MAX_STR = 120
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


class SchemaError(ValueError):
    """A report that is not in the allow-list."""


def own() -> dict:
    """the server's own part, as the file says."""
    return json.loads(resources.files(__package__).joinpath("schema.json").read_text())


def page_part() -> dict | None:
    """the page's part (its ``telemetry.json``), or None without the page."""
    try:
        from kranto.page.host_api import telemetry_schema
    except (ImportError, AttributeError):
        return None
    try:
        part = telemetry_schema()
    except Exception:  # noqa: BLE001 - a broken part leaves the page's keys out, nothing more
        return None
    return part if isinstance(part, dict) else None


def merge(base: dict, part: dict | None) -> dict:
    """``base`` with ``part``'s enums, patterns and lines added. An enum both name is the
    union (the server's ``route`` and the page's ``node`` stay apart; a shared name means the
    same list)."""
    out = json.loads(json.dumps(base))
    for section in ("enums", "patterns", "lines"):
        for k, v in ((part or {}).get(section) or {}).items():
            if section == "enums" and k in out["enums"]:
                out["enums"][k] = list(dict.fromkeys([*out["enums"][k], *v]))
            else:
                out.setdefault(section, {})[k] = v
    return out


@lru_cache(maxsize=1)
def union() -> dict:
    """The whole list, as this install has it."""
    return merge(own(), page_part())


def reset() -> None:
    union.cache_clear()
    _compiled.cache_clear()


# -- one value ---------------------------------------------------------------------------------

def value_ok(spec: dict, value, schema: dict) -> bool:
    kind = spec.get("type")
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "int":
        return (isinstance(value, int) and not isinstance(value, bool)
                and spec.get("min", 0) <= value <= spec.get("max", 2**53))
    if kind == "str":
        if not isinstance(value, str) or len(value) > spec.get("max_len", MAX_STR):
            return False
        if "enum" in spec:
            return value in (schema["enums"].get(spec["enum"]) or ())
        if "pattern" in spec:
            return re.fullmatch(schema["patterns"][spec["pattern"]], value) is not None
        return False                                  # a string is an enum or a pattern
    if kind == "list":
        items = spec.get("items") or {}
        return (isinstance(value, list) and len(value) <= spec.get("max_items", 20)
                and all(value_ok(items, v, schema) for v in value))
    if kind == "template":                            # an error message's template
        return isinstance(value, str) and template_ok(value, schema, spec.get("max_len", 200))
    if kind == "map":                                 # keys from an enum, values by a spec
        keys = schema["enums"].get(spec.get("keys")) or ()
        values = spec.get("values") or {}
        return (isinstance(value, dict) and len(value) <= len(keys)
                and all(k in keys and value_ok(values, v, schema) for k, v in value.items()))
    return False


_TEMPLATE_CHARS = frozenset(" '\"(),.:;[]=-<>")
_TEMPLATE_WORD = re.compile(r"[A-Za-z0-9_]+")


def template_ok(value: str, schema: dict, max_len: int = 200) -> bool:
    """A message template (``errtrace.template``): only the words of ``message_word``, the
    placeholders ``<x>`` and ``<n>``, and separators."""
    if len(value) > max_len:
        return False
    vocab = set(schema["enums"].get("message_word") or ())
    rest = value.replace("<x>", " ").replace("<n>", " ")
    if "<" in rest or ">" in rest:
        return False
    words = _TEMPLATE_WORD.findall(rest)
    if any(w not in vocab and w.lower() not in vocab for w in words):
        return False
    return not set(_TEMPLATE_WORD.sub("", rest)) - _TEMPLATE_CHARS


# -- local lines -------------------------------------------------------------------------------

def clean_line(name: str, fields: dict, schema: dict | None = None) -> tuple[dict | None, int]:
    """``(the fields the line may keep, how many were dropped)``; None when the line itself
    is not in the list or a field it needs is dropped."""
    schema = schema or union()
    spec = (schema.get("lines") or {}).get(name)
    if spec is None:
        return None, max(1, len(fields))
    kept, dropped = {}, 0
    for k, v in fields.items():
        s = spec.get(k)
        if s is not None and value_ok(s, v, schema):
            kept[k] = v
        else:
            dropped += 1
    if any(s.get("required") and k not in kept for k, s in spec.items()):
        return None, max(dropped, 1)
    return kept, dropped


# -- the report --------------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _compiled(blob: str) -> list[tuple[re.Pattern, dict]]:
    schema = json.loads(blob)
    out = []
    for key, spec in schema["daily"].items():
        parts, at = [], 0
        for m in _PLACEHOLDER.finditer(key):
            parts.append(re.escape(key[at:m.start()]))
            name = m.group(1)
            if name in schema["enums"]:
                values = schema["enums"][name]
                parts.append("(?:" + "|".join(map(re.escape, values)) + ")" if values
                             else "(?!)")
            elif name in schema["patterns"]:
                parts.append("(?:" + schema["patterns"][name].strip("^$") + ")")
            else:                  # the page's enum, without the page: no key matches
                parts.append("(?!)")
            at = m.end()
        parts.append(re.escape(key[at:]))
        out.append((re.compile("".join(parts)), spec))
    return out


def report_spec(key: str, schema: dict | None = None) -> dict | None:
    """The spec a report key falls under, or None when the list has no such key."""
    schema = schema or union()
    exact = schema["daily"].get(key)
    if exact is not None:
        return exact
    for pattern, spec in _compiled(json.dumps(schema, sort_keys=True)):
        if pattern.fullmatch(key):
            return spec
    return None


def check_resource(resource: dict, schema: dict | None = None) -> None:
    schema = schema or union()
    tier = resource.get("tier")
    for k, v in resource.items():
        spec = schema["resource"].get(k)
        if spec is None or spec.get("tier") == "relay":
            raise SchemaError(f"resource.{k} is not in the list")
        if spec.get("tier") == "detailed" and tier != "detailed":
            raise SchemaError(f"resource.{k} is sent only in the detailed tier")
        if not value_ok(spec, v, schema):
            raise SchemaError(f"resource.{k} has a value the list does not allow")
    for k in ("schema", "tier", "version"):
        if k not in resource:
            raise SchemaError(f"resource.{k} is missing")


def check_error(record: dict, schema: dict | None = None) -> None:
    """Raise ``SchemaError`` unless one error report's every key and value is allowed."""
    schema = schema or union()
    spec = schema["error"]
    for k, v in record.items():
        s = spec.get(k)
        if s is None:
            raise SchemaError(f"error.{k} is not in the list")
        if not value_ok(s, v, schema):
            raise SchemaError(f"error.{k} has a value the list does not allow")
    for k, s in spec.items():
        if s.get("required") and k not in record:
            raise SchemaError(f"error.{k} is missing")


def check_report(report: dict, schema: dict | None = None) -> None:
    """Raise ``SchemaError`` unless every key and value of the daily report is allowed."""
    schema = schema or union()
    if "day" not in report:
        raise SchemaError("day is missing")
    for k, v in report.items():
        spec = report_spec(k, schema)
        if spec is None:
            raise SchemaError(f"{k} is not in the list")
        if not value_ok(spec, v, schema):
            raise SchemaError(f"{k} has a value the list does not allow")
