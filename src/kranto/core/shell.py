"""The shell's arrangement: the ``shell:`` section of ``kranto.yaml``.

The home the person arranges is stored per install, here, never in the browser: the phone, the
desktop and ``kranto status`` read the same keys, and ``kranto export`` carries them. Every key
has a default, so nobody has to touch any of them.

- ``shell.layout`` (new · classic, new): the frame around the one set of pages. One layout
  since open-source wave 1 (D-2, PR 1.4): ``arrangement`` answers new whatever the file
  says, a file that says classic is kept as it is (still read, never rewritten), and a new write
  of classic is refused. ``shell.home`` and ``shell.doors``, its two keys until 0.5.8, are still
  read: ``migrate`` writes ``shell.layout`` in their place once, and a write of either is a
  write of the layout (false, which meant classic, refused like classic);
- ``shell.pins`` (cub ids, null): pinned on the home, in order; null is every installed cub in
  install order, six at most;
- ``shell.hidden`` (cub ids, []): off the home, Needs you and New (it still runs);
- ``shell.needs_cap`` (1 to 10, 3) and ``shell.new_cap`` (0 to 10, 4): rows in each;
- ``shell.needs_you.<id>`` (bool, by trust) and ``shell.new.<id>`` (bool, true): whether this
  cub may add rows to Needs you and to New;
- ``shell.widgets`` (a list, null): the home's widgets in order, each
  ``{id, size?, phone?, options?}``; null is the default home, 0.5.10's seven parts in their
  order (``core.home``). The pins, the caps and the allowances above stay the Cubs, Needs you
  and New widgets' own facts.

Needs you by trust: on for first-party and owner-made, off for reviewed, listed,
unreviewed and generated until the person allows it. ``write`` is the one writer: the key's rule
checks the value and the file is edited as text (comments and order stay), then
``settings.changed`` is published by the caller (``web/features_api``).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from . import home
from .manifest import ID, Setting
from .settings import SettingError, check, default_of

PINS_MAX = 6
LAYOUTS = ("new", "classic")
KEYS: dict[str, Setting] = {
    # new (the owner chose mock D on 2026-10-19 and the doors on 2026-10-20); classic was a
    # choice from 2026-10-21 until open-source wave 1 cut it: read, kept, drawn as new
    "shell.layout": Setting("enum", "new", choices=LAYOUTS,
                            words="the home and its doors (one layout; classic reads as new)"),
    "shell.pins": Setting("list", None, words="cubs pinned on the home, in order (at most 6)"),
    "shell.hidden": Setting("list", [], words="cubs off the home, Needs you and New"),
    "shell.needs_cap": Setting("int", 3, lo=1, hi=10, words="rows in Needs you at most"),
    "shell.new_cap": Setting("int", 4, lo=0, hi=10, words="rows in New today at most"),
    "shell.widgets": Setting("list", None, words="the home's widgets in order (null: the "
                             "default home)"),
}
PER_CUB = ("needs_you", "new")
# the layout's two keys until 0.5.8 (shell.home: the home or the navigator; shell.doors: the
# doors' pages or 0.4.10's): read, never offered, written as shell.layout
LEGACY = ("home", "doors")


def legacy_layout(home: Any, doors: Any) -> str:
    """The layout two old switches meant: false in either is the navigator, classic."""
    return "classic" if home is False or doors is False else "new"

# the layout a write may still choose (classic is read and kept, never written: D-2)
WRITABLE_LAYOUTS = ("new",)


def _writable(key: str, clean: Any) -> None:
    if key == "shell.layout" and clean not in WRITABLE_LAYOUTS:
        raise SettingError("shell.layout is new: Kranto has one layout (a file that says "
                           "classic is kept, and reads as new)")


# features that are one of the four fixed doors (Watch, Ideas, Build, News), not cubs
DOOR_FEATURES = ("news",)
TRUSTED = ("first-party", "owner")


def needs_you_default(trust: str) -> bool:
    return trust in TRUSTED


def _ids(key: str, value: object) -> list[str] | None:
    if value is None and key == "shell.pins":
        return None
    if not isinstance(value, list) or not all(isinstance(x, str) and ID.fullmatch(x)
                                              for x in value):
        raise SettingError(f"{key} is a list of cub ids")
    if len(set(value)) != len(value):
        raise SettingError(f"{key} names a cub twice")
    if key == "shell.pins" and len(value) > PINS_MAX:
        raise SettingError(f"{key} pins at most {PINS_MAX}; the rest sit under More cubs")
    return list(value)


def check_value(key: str, value: object) -> Any:
    """The value, normalised, or SettingError saying what the key takes."""
    if key in ("shell.pins", "shell.hidden"):
        return _ids(key, value)
    if key == "shell.widgets":
        return home.check_widgets(value)
    if key in KEYS:
        return check(key, KEYS[key], value)
    parts = key.split(".")
    if len(parts) == 3 and parts[0] == "shell" and parts[1] in PER_CUB \
            and ID.fullmatch(parts[2]):
        if value is not None and not isinstance(value, bool):
            raise SettingError(f"{key} is true or false (null: by its trust)")
        return value
    raise SettingError(f"{key} is not one of the shell's keys")


def parse(raw: object) -> dict[str, Any]:
    """``{key: value}`` from the file's ``shell:`` section over the defaults; the per-cub keys
    as ``needs_you`` and ``new`` mappings. A key the shell does not know is refused."""
    from ..config import ConfigError

    raw = raw or {}
    if not isinstance(raw, dict):
        raise ConfigError("shell: expected a mapping")
    out: dict[str, Any] = {k: default_of(r) for k, r in KEYS.items()}
    out["needs_you"], out["new"] = {}, {}
    old: dict[str, Any] = {}
    for k, v in raw.items():
        if k in LEGACY:
            if not isinstance(v, bool):
                raise ConfigError(f"shell.{k} is true or false (shell.layout says it now)")
            old[k] = v
            continue
        if k in PER_CUB:
            if not isinstance(v, dict):
                raise ConfigError(f"shell.{k}: expected a mapping of cub id to true or false")
            for cid, on in v.items():
                try:
                    got = check_value(f"shell.{k}.{cid}", on)
                except SettingError as exc:
                    raise ConfigError(str(exc)) from None
                if got is not None:
                    out[k][str(cid)] = got
            continue
        key = f"shell.{k}"
        if key not in KEYS:
            raise ConfigError(f"unknown keys in shell: {key}")
        try:
            out[key] = check_value(key, v)
        except SettingError as exc:
            raise ConfigError(str(exc)) from None
    if old and "layout" not in raw:
        out["shell.layout"] = legacy_layout(old.get("home"), old.get("doors"))
    return out


def values(cfg: Any) -> dict[str, Any]:
    got = getattr(cfg, "shell", None)
    return dict(got) if got else parse({})


def _on(cfg: Any, feature: Any) -> bool:
    """Whether ``feature`` is on (``core.registry.enabled``); one that cannot say is on."""
    try:
        from .registry import enabled
        return bool(enabled(cfg, feature))
    except Exception:  # noqa: BLE001 - a feature or a config the registry cannot read
        return True


def arrangement(cfg: Any, features: Any) -> dict[str, Any]:
    """What the home draws: the shell's values and, for each installed feature that is not
    one of the four doors, its pin, its place and whether it may add rows."""
    v = values(cfg)
    # a feature that is off has no pin, no tile and no row here: turned on,
    # it is back where it was, the pins it had kept in the file
    cubs = [f for f in features if f.id not in DOOR_FEATURES and _on(cfg, f)]
    order = [f.id for f in cubs]
    hidden = [x for x in v["shell.hidden"] if x in order]
    pins = v["shell.pins"]
    if pins is None:
        pins = [x for x in order if x not in hidden][:PINS_MAX]
    pins = [x for x in pins if x in order and x not in hidden]
    rows = []
    for f in cubs:
        rows.append({"id": f.id, "trust": f.trust, "pinned": f.id in pins,
                     "place": pins.index(f.id) if f.id in pins else None,
                     "hidden": f.id in hidden,
                     "needs_you": v["needs_you"].get(f.id, needs_you_default(f.trust)),
                     "new": v["new"].get(f.id, True)})
    # one layout: new whatever the file says (the file keeps it). home and doors:
    # what a page of 0.5.8 or older reads (the server and its page may be a release apart)
    return {"layout": "new", "home": True, "doors": True,
            "pins": pins, "hidden": hidden,
            "needs_cap": v["shell.needs_cap"], "new_cap": v["shell.new_cap"], "cubs": rows,
            "pins_max": PINS_MAX,
            # the home's widgets in order, resolved (core.home.resolve); custom: the person
            # arranged them (shell.widgets is set), else the default home
            "widgets": home.resolve(v.get("shell.widgets"), [f for f in features if _on(cfg, f)]),
            "custom": v.get("shell.widgets") is not None,
            "keys": [{"key": k, "type": r.type, "default": default_of(r), "lo": r.lo,
                      "hi": r.hi, "words": r.words} for k, r in KEYS.items()]}


def write(cfg: Any, key: str, value: object) -> dict[str, Any]:
    """Write one key (``value`` None on a per-cub key, or ``reset``, puts the default back by
    writing it) and return the shell's values as they now are."""
    from .. import config as config_mod
    from ..setup import write_config_values

    if key in (f"shell.{k}" for k in LEGACY):        # an old switch: the layout it meant
        if not isinstance(value, bool):
            raise SettingError(f"{key} is true or false")
        key, value = "shell.layout", "new" if value else "classic"
    clean = check_value(key, value)
    _writable(key, clean)
    path = config_mod.config_path(cfg.root)
    if path is None:
        raise SettingError("this Kranto has no kranto.yaml")
    parts = tuple(key.split("."))
    if not all(re.fullmatch(r"[a-z0-9_]+", p) for p in parts):
        raise SettingError(f"{key} is not a config key")
    write_config_values(path, {parts: clean})
    now = values(cfg)
    if len(parts) == 3:
        now[parts[1]] = {k: v for k, v in {**now[parts[1]], parts[2]: clean}.items()
                         if v is not None}
    else:
        now[key] = clean
    return now


def write_many(cfg: Any, values: dict[str, Any]) -> dict[str, Any]:
    """Several keys in one write (Arrange's Undo after Reset to default puts the whole
    arrangement back at once): each checked by its key's rule first, so either every key is
    written or none is. Returns the shell's values as they now are."""
    from .. import config as config_mod
    from ..setup import write_config_values

    if not isinstance(values, dict) or not values:
        raise SettingError("values is a mapping of shell keys")
    clean = {}
    for key, value in values.items():
        key = str(key)
        if key in (f"shell.{k}" for k in LEGACY):
            raise SettingError(f"{key} is written as shell.layout")
        parts = tuple(key.split("."))
        if not all(re.fullmatch(r"[a-z0-9_]+", p) for p in parts):
            raise SettingError(f"{key} is not a config key")
        clean[parts] = check_value(key, value)
        _writable(key, clean[parts])
    path = config_mod.config_path(cfg.root)
    if path is None:
        raise SettingError("this Kranto has no kranto.yaml")
    write_config_values(path, clean)
    return values_of_file(cfg)


def values_of_file(cfg: Any) -> dict[str, Any]:
    """The shell's values as ``kranto.yaml`` holds them now."""
    from .. import config as config_mod
    path = config_mod.config_path(cfg.root)
    raw = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("shell") if path else None
    return parse(raw)


RESET = ("shell.pins", "shell.hidden", "shell.needs_cap", "shell.new_cap", "shell.widgets")


def reset(cfg: Any) -> dict[str, Any]:
    """Arrange's Reset to defaults: the arrangement keys back to their defaults (written, so
    the file says so), each cub's allowances back to its trust's. ``shell.layout`` stays."""
    from .. import config as config_mod
    from ..setup import write_config_values

    path = config_mod.config_path(cfg.root)
    if path is None:
        raise SettingError("this Kranto has no kranto.yaml")
    v = values(cfg)
    out = {tuple(k.split(".")): default_of(KEYS[k]) for k in RESET}
    for kind in PER_CUB:
        for cid in v[kind]:
            if re.fullmatch(r"[a-z0-9_]+", cid):
                out[("shell", kind, cid)] = None
    write_config_values(path, out)
    fresh = parse({})
    fresh["shell.layout"] = v["shell.layout"]
    return fresh


def migrate(root: Path) -> str | None:
    """Once, as Kranto starts: a ``kranto.yaml`` whose ``shell:`` block still holds ``home:`` or
    ``doors:`` gets ``layout:`` in their place (the layout they meant, or the one already
    written), their lines removed and every other line as it was; the file is replaced in one
    step. Returns the layout written, or None when there was nothing to do (no file, no old
    key, or a ``shell:`` written in flow style, whose old keys go on being read)."""
    from .. import config as config_mod
    from ..setup import set_yaml_value

    path = config_mod.config_path(root)
    if path is None or not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    raw = (yaml.safe_load(text) or {}).get("shell")
    if not isinstance(raw, dict) or not set(raw) & set(LEGACY):
        return None
    layout = raw.get("layout")
    if layout not in LAYOUTS:
        layout = legacy_layout(raw.get("home"), raw.get("doors"))
    lines = text.splitlines(keepends=True)
    head = re.compile(r"^shell:\s*(#.*)?$")
    start = next((i for i, ln in enumerate(lines) if head.match(ln.rstrip("\n"))), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() and not lines[i].startswith((" ", "\t", "#"))), len(lines))
    gone = re.compile(r"^  (home|doors):")
    text = set_yaml_value("".join(ln for i, ln in enumerate(lines)
                                  if not (start < i < end and gone.match(ln))),
                          "shell", "layout", layout)
    now = (yaml.safe_load(text) or {}).get("shell") or {}
    if now.get("layout") != layout or set(now) & set(LEGACY):
        return None
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return layout
