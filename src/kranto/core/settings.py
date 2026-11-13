"""A feature's settings (``settings``,): its own ``kranto.yaml`` section.

Each key is declared in the manifest with its type, default and bounds; ``parse_all`` checks
every feature's section when the config is loaded (a bad value is a ``ConfigError`` like any
other section's, and a key the manifest does not declare is refused), and fills the defaults.
``write`` is the one way the page changes one: the key's rule checks the value, sensitive keys
need the house confirm (the caller's job: ``web/features_api``), and a key marked ``by_hand``
(``invest.live.enabled``) is never written by Kranto: the owner writes it in the file.

A key of type ``topics`` is a list of topic ids (none: every topic); the page draws the core's
topic picker for it, whatever feature or cub declares it.

Keys are dotted: ``news.hour`` is ``hour`` in ``news:``; ``invest.live.per_trade_usd`` is
``per_trade_usd`` under ``live:`` in ``invest:``.
"""

from __future__ import annotations

import re

from .manifest import Setting


class SettingError(ValueError):
    pass


def _features():
    """Kranto's own features and the installed cubs."""
    from .registry import features
    return features()


def _first_party():
    from ..features import FEATURES
    return FEATURES


_RAW: dict = {}


def _raw_section(cfg, fid: str):
    """A section of ``kranto.yaml`` as written (a cub's, which ``config.load`` leaves alone),
    read again when the file changes."""
    import yaml

    from .. import config as config_mod
    path = config_mod.config_path(cfg.root)
    if path is None:
        return None
    mtime = path.stat().st_mtime_ns
    if _RAW.get("path") != path or _RAW.get("mtime") != mtime:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            raw = {}
        _RAW.update(path=path, mtime=mtime, raw=raw if isinstance(raw, dict) else {})
    return _RAW["raw"].get(fid)


def _no_secrets(feature, values: dict) -> dict:
    """A cub's setting never holds a key: a secret-shaped value is null (the doctor says
    so); connect the service under Connections instead."""
    from ..scrub import secret_shaped
    out = {}
    for k, v in values.items():
        texts = v if isinstance(v, list) else [v]
        out[k] = None if any(isinstance(t, str) and secret_shaped(t) for t in texts) else v
    return out


def cub_section(cfg, feature) -> dict:
    """A cub's own section: its keys as written, checked by its manifest's rules, a value
    shaped like a secret dropped; a section that does not parse falls back to the defaults
    (a cub's settings never stop Kranto from starting)."""
    import logging

    from ..config import ConfigError
    try:
        return _no_secrets(feature, parse_section(feature, _raw_section(cfg, feature.id)))
    except ConfigError as exc:
        logging.getLogger("kranto.core.settings").warning(
            "%s's section of kranto.yaml is ignored: %s", feature.id, exc)
        return parse_section(feature, {})


# a list setting's choice whose feature left Kranto (cut 2): a stored value naming it
# still loads, the choice is dropped, and the page never offers it again
RETIRED_CHOICES: dict[str, tuple[str, ...]] = {"news.sources": ("radar",)}


def check(key: str, rule: Setting, value):
    """The value, normalised, or SettingError saying what the key takes."""
    t = rule.type
    if value is None and rule.default is None and t in ("usd", "float", "int", "str"):
        return None                                  # null: off or uncapped, by the default
    if t == "bool":
        if not isinstance(value, bool):
            raise SettingError(f"{key} is true or false")
        return value
    if t in ("int",):
        if isinstance(value, bool) or not isinstance(value, int):
            raise SettingError(f"{key} is a whole number")
    elif t in ("float", "usd"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise SettingError(f"{key} is a number" + (" of USD, or null for no cap"
                                                        if t == "usd" else ""))
        value = float(value)
        if t == "usd" and value < 0:
            raise SettingError(f"{key} is USD, 0 or more")
    elif t == "enum":
        if value not in rule.choices:
            raise SettingError(f"{key} is one of {', '.join(map(str, rule.choices))}")
        return value
    elif t == "str":
        if not isinstance(value, str) or len(value) > 500:
            raise SettingError(f"{key} is text")
        return value
    elif t == "topics":
        # topic ids; an id written as digits (an older list key's value) is read as the number
        if not isinstance(value, list) or len(value) > 200 or not all(
                (isinstance(x, int) and not isinstance(x, bool) and x > 0)
                or (isinstance(x, str) and x.isdigit() and int(x) > 0) for x in value):
            raise SettingError(f"{key} is a list of topic ids")
        return sorted({int(x) for x in value})
    elif t == "list":
        if not isinstance(value, list) or not all(isinstance(x, str | int | float)
                                                  for x in value) or len(value) > 200:
            raise SettingError(f"{key} is a list")
        value = [x for x in value if x not in RETIRED_CHOICES.get(key, ())]
        if rule.choices and any(x not in rule.choices for x in value):
            raise SettingError(f"{key} takes some of {', '.join(map(str, rule.choices))}")
        return list(value)
    if rule.lo is not None and value < rule.lo or rule.hi is not None and value > rule.hi:
        raise SettingError(f"{key} is from {rule.lo} to {rule.hi}")
    return value


def _walk(raw: dict, path: list[str]):
    node = raw
    for p in path:
        if not isinstance(node, dict) or p not in node:
            return False, None
        node = node[p]
    return True, node


def _declared_paths(fid: str, keys: dict) -> set[tuple[str, ...]]:
    out = set()
    for key in keys:
        parts = tuple(key.split(".")[1:])
        for i in range(1, len(parts)):
            out.add(parts[:i])
    return out


def parse_section(feature, raw: dict | None) -> dict:
    """``{key: value}`` for every declared key, the file's value or the default."""
    from ..config import ConfigError

    raw = raw or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{feature.id}: expected a mapping")
    keys = feature.settings.keys
    leaves = {tuple(k.split(".")[1:]) for k in keys}
    branches = _declared_paths(feature.id, keys)

    def unknown(node, prefix=()):
        for k, v in node.items():
            path = (*prefix, str(k))
            if path in leaves:
                continue
            if path in branches and isinstance(v, dict):
                yield from unknown(v, path)
            else:
                yield ".".join((feature.id, *path))

    bad = sorted(unknown(raw))
    if bad:
        raise ConfigError(f"unknown keys in {feature.id}: {', '.join(bad)}")
    out = {}
    for key, rule in keys.items():
        found, value = _walk(raw, key.split(".")[1:])
        if not found:
            out[key] = default_of(rule)
            continue
        try:
            out[key] = check(key, rule, value)
        except SettingError as exc:
            raise ConfigError(str(exc)) from None
    return out


def on_stable() -> bool:
    """This Kranto runs a stable release (``X.Y.Z``), not a nightly build (``X.Y.0.devN``), an
    old rc or a build from git: the line whose defaults ``Setting.default_stable`` gives."""
    from .. import __version__

    return re.fullmatch(r"\d+\.\d+\.\d+", str(__version__ or "")) is not None


def default_of(rule, stable: bool | None = None):
    """A setting's default on this install's line: ``default_stable`` on a
    stable release when the setting has one, else ``default``. A list is copied."""
    stable = on_stable() if stable is None else stable
    d = rule.default_stable if (stable and rule.default_stable is not None) else rule.default
    return list(d) if isinstance(d, list | tuple) else d


def stable_defaults() -> list[dict]:
    """Every setting of Kranto's own whose stable default keeps the old behaviour: what a
    promotion's notes and the Promote row name as "off on stable" (``kranto settings
    stable-defaults``)."""
    from . import shell as shell_mod

    rules = [(k, r) for f in _first_party() for k, r in f.settings.keys.items()]
    rules += list(shell_mod.KEYS.items())
    return [{"key": k, "default": r.default, "default_stable": r.default_stable}
            for k, r in rules
            if r.default_stable is not None and r.default_stable != r.default]


def parse_all(raw: dict) -> dict:
    """Kranto's own features' sections, checked when the config loads (a cub's section is read
    when the cub needs it: ``cub_section``)."""
    return {f.id: parse_section(f, raw.get(f.id)) for f in _first_party()}


def section(cfg, fid: str) -> dict:
    """A feature's settings as loaded (the defaults when the config has no section)."""
    got = (getattr(cfg, "features", None) or {}).get(fid)
    if got is not None:
        return dict(got)
    feature = next(f for f in _features() if f.id == fid)
    if getattr(feature, "data", None) is not None and getattr(cfg, "root", None) is not None:
        return cub_section(cfg, feature)
    return parse_section(feature, {})


def checked(fid: str, key: str, value):
    """``value`` as ``write`` would keep it for ``fid``'s ``key``, or SettingError; writes
    nothing (the verbs' door checks a prepared press with it: PAR)."""
    feature = next((f for f in _features() if f.id == fid), None)
    if feature is None:
        raise SettingError(f"no feature {fid}")
    rule = feature.settings.keys.get(key)
    if rule is None:
        raise SettingError(f"{key} is not one of {fid}'s settings")
    if rule.by_hand:
        raise SettingError(f"{key} is written by hand in kranto.yaml, never from the page")
    clean = check(key, rule, value)
    if getattr(feature, "data", None) is not None and _no_secrets(feature, {key: clean})[key] \
            is None and clean is not None:
        raise SettingError(f"{key}: a value shaped like a key or a token; a cub never holds "
                           "one (connect the service under Connections)")
    return clean


def write(cfg, fid: str, key: str, value) -> dict:
    """Write one key to ``kranto.yaml`` and return the feature's settings as they now are.
    Refuses an undeclared key, a ``by_hand`` key and a value its rule does not take."""
    from .. import config as config_mod
    from ..setup import write_config_values

    clean = checked(fid, key, value)
    path = config_mod.config_path(cfg.root)
    if path is None:
        raise SettingError("this Kranto has no kranto.yaml")
    write_config_values(path, {tuple([fid, *key.split(".")[1:]]): clean})
    current = dict(section(cfg, fid))
    current[key] = clean
    return current


def describe(feature, values: dict) -> list[dict]:
    """The rows Settings draws: key, value, type, choices, bounds, words, sensitive, by hand,
    and its place on the feature's Settings page: its group's heading and Advanced."""
    st = feature.settings
    stable = on_stable()
    return [{"key": k, "value": values.get(k), "type": r.type,
             "default": default_of(r, stable),
             # the other line's default, when it differs (Settings shows "nightly's default is
             # ...", or stable's): None when both lines share one
             "default_other": (r.default if stable else r.default_stable)
             if r.default_stable is not None and r.default_stable != r.default else None,
             "line": "stable" if stable else "nightly",
             "choices": list(r.choices), "lo": r.lo, "hi": r.hi, "words": r.words,
             "sensitive": k in st.sensitive, "by_hand": r.by_hand,
             "per_topic": k in st.per_topic, "group": r.group, "advanced": r.advanced}
            for k, r in st.keys.items()]
