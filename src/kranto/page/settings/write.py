"""Writing the page's settings file, ``loop.yaml``.

A value is set, or unset (back to the default in ``store.DEFAULTS``), at a dotted path such
as ``term.daily_usd``. The file is edited as text, so the owner's comments and the
order of keys survive; the result is parsed and checked before it replaces the file in one
step. A file the text edit cannot handle (a flow-style mapping on the path) is rewritten
from its parsed form instead, keeping its leading comment.

Only the keys in ``RULES``, each checked by ``check``, are written from a request
(``POST api/term/settings``); the console's own settings (``ask``) are written by
``term/service.py``, and the wizard writes ``build.claude_command``.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml

UNSET = object()


def _scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list):
        return json.dumps(value)                 # a flow sequence: JSON is YAML
    return json.dumps(str(value))


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _quiet(line: str) -> bool:
    """Blank or a comment: belongs to no key."""
    return not line.strip() or line.lstrip().startswith("#")


def _span(lines: list[str], lo: int, hi: int, ind: int, key: str) -> tuple[int, int] | None:
    pat = re.compile(rf"^ {{{ind}}}{re.escape(key)}:(\s|$)")
    for i in range(lo, hi):
        if pat.match(lines[i]):
            end = i + 1
            while end < hi and (_quiet(lines[end]) or _indent(lines[end]) > ind):
                end += 1
            while end > i + 1 and _quiet(lines[end - 1]):
                end -= 1
            return i, end
    return None


def _split(head: str) -> tuple[str, str]:
    """A ``key: value  # note`` line's value and comment (with its leading space)."""
    rest = head.rstrip("\n").split(":", 1)[1]
    m = re.search(r"\s+#.*$", rest)
    return (rest[:m.start()], m.group(0)) if m else (rest, "")


class _Flow(Exception):
    """The path runs through a flow-style mapping: the text edit gives up."""


def edit_text(text: str, keys: tuple[str, ...], value=UNSET) -> str:
    """``text`` with ``keys`` set to ``value``, or removed when ``value`` is ``UNSET``."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lo, hi, ind = 0, len(lines), 0
    parent: int | None = None
    for d, key in enumerate(keys):
        last = d == len(keys) - 1
        sp = _span(lines, lo, hi, ind, key)
        if sp is None:
            if value is UNSET:
                return "".join(lines)
            at = hi
            while at > lo and _quiet(lines[at - 1]):
                at -= 1
            block = [" " * (ind + 2 * j) + k + ":" +
                     (f" {_scalar(value)}\n" if j == len(keys) - d - 1 else "\n")
                     for j, k in enumerate(keys[d:])]
            lines[at:at] = block
            return "".join(lines)
        i, end = sp
        val, note = _split(lines[i])
        if last:
            if value is UNSET:
                del lines[i:end]
                if parent is not None and not _has_children(lines, parent):
                    # an empty block would parse as null: keep it a mapping
                    note = _split(lines[parent])[1]
                    lines[parent] = lines[parent].split(":", 1)[0] + ": {}" + note + "\n"
                return "".join(lines)
            lines[i:end] = [" " * ind + key + ": " + _scalar(value) + note + "\n"]
            return "".join(lines)
        v = val.strip()
        if v in ("{}", "null", "~"):
            lines[i] = " " * ind + key + ":" + note + "\n"
        elif v:
            raise _Flow(".".join(keys[:d + 1]))
        child = next((_indent(ln) for ln in lines[i + 1:end] if not _quiet(ln)), ind + 2)
        parent, lo, hi, ind = i, i + 1, end, child
    return "".join(lines)


def _has_children(lines: list[str], at: int) -> bool:
    ind = _indent(lines[at])
    for line in lines[at + 1:]:
        if not _quiet(line):
            return _indent(line) > ind
    return False


def _get(data, keys):
    for k in keys:
        if not isinstance(data, dict) or k not in data:
            return UNSET
        data = data[k]
    return data


def _rewrite(text: str, keys: tuple[str, ...], value) -> str:
    data = yaml.safe_load(text) or {}
    node = data
    for k in keys[:-1]:
        if not isinstance(node.get(k), dict):
            node[k] = {}
        node = node[k]
    if value is UNSET:
        node.pop(keys[-1], None)
    else:
        node[keys[-1]] = value
    head = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        head.append(line)
    return "\n".join(head + [yaml.safe_dump(data, sort_keys=False).rstrip()]) + "\n"


def write(path: Path, keys: tuple[str, ...], value=UNSET) -> None:
    """Set (or unset) ``keys`` in the YAML file at ``path`` and replace it in one step."""
    path = Path(path)
    text = path.read_text() if path.exists() else ""
    try:
        new = edit_text(text, keys, value)
        ok = _get(yaml.safe_load(new) or {}, keys) == value if value is not UNSET \
            else _get(yaml.safe_load(new) or {}, keys) is UNSET
    except (_Flow, yaml.YAMLError):
        ok = False
    if not ok:
        new = _rewrite(text, keys, value)
    parsed = yaml.safe_load(new) or {}
    if (value is UNSET and _get(parsed, keys) is not UNSET) or \
            (value is not UNSET and _get(parsed, keys) != value):
        raise ValueError(f"could not set {'.'.join(keys)} in {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(new)
    try:
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


REPO_NAME = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}")


# Every loop.yaml setting the page writes from a request, by its dotted key, with its check:
# ("bool",) | ("enum", choices) | ("usd",) (a number of dollars, or empty for no cap). A key not
# here is set in loop.yaml by hand on purpose: commands, paths and the network allow-lists
# are never written from a request.
RULES: dict[str, tuple] = {
    "term.enabled": ("enum", (None, True, False)), "term.daily_usd": ("usd",),
    "term.allow_api_key": ("bool",)}
_WORDS = {True: "true", False: "false", None: "empty"}


def check(key: str, value):
    """A loop.yaml value from a request, checked against ``RULES``; ValueError says why, in
    words. Never a model."""
    rule = RULES.get(key)
    if rule is None:
        raise ValueError(f"{key or '(no key)'} is not a setting the app writes; set it in "
                         "loop.yaml")
    return checked(rule, key, value)


def checked(rule: tuple, key: str, value):
    kind = rule[0]
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{key} is true or false")
        return value
    if kind == "enum":
        if value == "" and None in rule[1]:
            value = None
        if value not in rule[1] or (isinstance(value, bool) and not any(
                c is value for c in rule[1])):
            raise ValueError(f"{key} is one of " + ", ".join(
                _WORDS.get(c, str(c)) if not isinstance(c, str) else c for c in rule[1]))
        return value
    if kind == "usd":
        if isinstance(value, str) and value.strip().lower() in ("none", "null"):
            return None
        if isinstance(value, str) and value:          # a form's field: a number as text
            try:
                value = float(value)
            except ValueError:
                pass
        return usd_or_none(value, key)
    raise ValueError(f"{key}: no check of kind {kind}")


def usd_or_none(value, what: str) -> float | None:
    """A cap from a request: None (no cap) or a number of USD above 0."""
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value <= 1e6 \
            or value != value:
        raise ValueError(f"{what} must be a number of USD above 0, or empty for no cap")
    return round(float(value), 2)
