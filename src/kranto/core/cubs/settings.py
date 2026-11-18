"""The ``cubs:`` section of ``kranto.yaml``: the owner's switches and limits.

Closed keys, a map per cub, one writer (``write``) like the shell's. Every key has a default, so
nobody has to write any of them:

- ``cubs.enabled`` (true): the global switch; false stops every cub and spawns none;
- ``cubs.max_running`` (1 to 8, 3), ``cubs.idle_s`` (0 to 600, 60): processes at once and the
  keep-alive after the last request;
- ``cubs.auto_update`` (true since 2026-10-23, the owner's rule), ``cubs.check_updates``
  (true): the daily ``cubs.updates`` (updates.py) applies by itself an update that adds no
  permission and no send and runs on this Kranto; any other waits for the owner's press;
- ``cubs.auto_update_unreviewed`` (false): the same for a cub from a source nobody reviewed (a git
  address: trust ``listed``, ``unreviewed`` or ``generated``); off, each of its updates waits for
  the owner's approval, whatever it asks;
- ``cubs.default_monthly_usd`` (5) and ``cubs.default_calls_per_day`` (200): what a cub that is
  not the owner's gets without a cap of its own (D6);
- ``cubs.min_sdk`` (null): refuse an older SDK at hello;
- ``cubs.allow_rlimits`` (false): where no systemd user manager caps a cub's processes and CPU
  (``rlimits`` mode), only the owner's cubs run unless this is true; written by hand;
- ``cubs.developer`` (false): the cub shop (Available, Made by Kranto, a cub added from outside,
  checking, updating or removing one by hand); off, the page shows your installed cubs and their
  approvals, and the shop's verbs are not offered. The daily update of installed cubs still runs;
- ``cubs.<id>.enabled`` (true): the owner's switch for one cub;
- ``cubs.<id>.live`` (``[]``): the request kinds that are live for this cub; added on the page
  only (the house confirm), removed from the page or the command line (D5);
- ``cubs.<id>.monthly_usd``, ``.calls_per_day``: its caps (by trust when unset: the owner's
  cubs uncapped, others the defaults above);
- ``cubs.<id>.tickets_per_day``: lowers, never raises, a kind's daily cap;
- ``cubs.<id>.memory_mb``, ``.pids``, ``.cpu_pct``, ``.tmp_mb``, ``.kv_mb``: the process's
  limits and the key-value quota, under the tier's ceilings for a stranger's cub.

The registry's state (installed, paused, removed) is not a setting: it changes by runtime
events. The owner's switch is ``cubs.<id>.enabled``.
"""

from __future__ import annotations

import re
import time

from ..manifest import ID, Setting
from ..settings import SettingError, check

GLOBAL: dict[str, Setting] = {
    "cubs.enabled": Setting("bool", True, words="cubs run (off: none runs or starts)"),
    "cubs.max_running": Setting("int", 3, lo=1, hi=8, words="cub processes at once"),
    "cubs.idle_s": Setting("int", 60, lo=0, hi=600,
                           words="seconds a cub's process stays up after its last request"),
    "cubs.auto_update": Setting("bool", True,
                                words="apply a cub's update by itself when it adds no "
                                      "permission and no send and runs on this Kranto"),
    "cubs.auto_update_unreviewed": Setting(
        "bool", False, words="apply by itself also the update of a cub from a source nobody "
                             "reviewed (a git address); off, its updates wait for your approval"),
    "cubs.check_updates": Setting("bool", True, words="look for cubs' updates daily"),
    "cubs.default_monthly_usd": Setting("usd", 5.0,
                                        words="a stranger's cub: model and search a month"),
    "cubs.default_calls_per_day": Setting("int", 200, lo=10, hi=10000,
                                          words="a stranger's cub: calls to your accounts "
                                                "and the web a day"),
    "cubs.min_sdk": Setting("str", None, words="the oldest cub SDK this Kranto runs"),
    "cubs.allow_rlimits": Setting("bool", False,
                                  words="run cubs that are not yours on a machine that cannot "
                                        "cap their processes (no systemd user manager)"),
    #.2: the cub shop is a developer's, off unless set
    "cubs.developer": Setting("bool", False,
                              words="the cub shop: Available, Made by Kranto, adding a cub from "
                                    "outside and its checks (off: your installed cubs only)"),
}
PER_CUB: dict[str, Setting] = {
    "enabled": Setting("bool", True, words="this cub runs"),
    "live": Setting("list", [], words="what it may do for real (each confirmed on the page)"),
    "monthly_usd": Setting("usd", None, words="its model and search a month"),
    "calls_per_day": Setting("int", None, lo=10, hi=10000,
                             words="its calls to your accounts and the web a day"),
    "tickets_per_day": Setting("int", None, lo=1, hi=50,
                               words="how often it may ask you, of a kind, a day"),
    "memory_mb": Setting("int", 512, lo=64, hi=4096, words="its memory"),
    "pids": Setting("int", 64, lo=8, hi=512, words="its processes and threads"),
    "cpu_pct": Setting("int", 100, lo=10, hi=400, words="its CPU (100: one core)"),
    "tmp_mb": Setting("int", 64, lo=16, hi=1024, words="its scratch space"),
    "kv_mb": Setting("int", 8, lo=1, hi=64, words="its stored data"),
}
# What a cub that is not the owner's, nor reviewed, may be given at most.
CEILINGS = {"memory_mb": 1024, "pids": 128, "cpu_pct": 200}
CEILING_TIERS = ("listed", "unreviewed", "generated")
# The owner's own cubs inherit Kranto's uncapped rule; others get the defaults above (D6).
UNCAPPED_TIERS = ("owner",)
GLOBAL_NAMES = tuple(k.split(".", 1)[1] for k in GLOBAL)


def _default(rule: Setting):
    return list(rule.default) if isinstance(rule.default, list | tuple) else rule.default


def _check_global(key: str, value):
    rule = GLOBAL[key]
    if value is None and rule.type == "usd":
        return None                      # null: no default cap for a stranger's cub
    return check(key, rule, value)


def check_per_cub(cid: str, name: str, value, *, trust: str | None = None):
    """``cubs.<id>.<name>``'s value, normalised, or SettingError naming the key."""
    key = f"cubs.{cid}.{name}"
    rule = PER_CUB.get(name)
    if rule is None:
        raise SettingError(f"{key} is not one of a cub's keys ({', '.join(PER_CUB)})")
    if name == "live":
        from .. import tickets
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise SettingError(f"{key} is a list of request kinds")
        unknown = [k for k in value if k not in tickets.kind_names()]
        if unknown:
            raise SettingError(f"{key}: no request kind {', '.join(unknown)}")
        if len(set(value)) != len(value):
            raise SettingError(f"{key} names a kind twice")
        return list(value)
    if value is None and name in ("monthly_usd", "calls_per_day", "tickets_per_day"):
        return None
    clean = check(key, rule, value)
    if trust in CEILING_TIERS and name in CEILINGS and clean > CEILINGS[name]:
        raise SettingError(f"{key}: a {trust} cub may have at most {CEILINGS[name]}")
    return clean


def parse(raw) -> dict:
    """``{key: value}`` for the global keys over their defaults, and ``per``: each cub's
    keys as written (``{id: {name: value}}``). A key the section does not know is refused."""
    from ...config import ConfigError

    raw = raw or {}
    if not isinstance(raw, dict):
        raise ConfigError("cubs: expected a mapping")
    out: dict = {k: _default(r) for k, r in GLOBAL.items()}
    out["per"] = {}
    for k, v in raw.items():
        key = f"cubs.{k}"
        try:
            if key in GLOBAL:
                out[key] = _check_global(key, v)
                continue
            if not isinstance(k, str) or not ID.fullmatch(k):
                raise SettingError(f"unknown keys in cubs: {key}")
            if not isinstance(v, dict):
                raise SettingError(f"{key}: expected a mapping of its keys")
            out["per"][k] = {str(n): check_per_cub(k, str(n), x) for n, x in v.items()}
        except SettingError as exc:
            raise ConfigError(str(exc)) from None
    return out


_FRESH: dict = {}


def values(cfg) -> dict:
    """The section in force: as loaded with the config, and read again from ``kranto.yaml``
    whenever the file changes after that (``kranto cub dry`` from a terminal, a hand edit, the
    page's write), so a switch reaches the running server at the next call. A section that no
    longer parses falls back to the defaults, where every kind is dry and nothing is capped
    above its default (never to a stale ``live``)."""
    got = getattr(cfg, "cubs", None) if cfg is not None else None
    loaded = dict(got) if got else parse({})
    from ... import config as config_mod
    root = getattr(cfg, "root", None)
    path = config_mod.config_path(root) if root is not None else None
    if path is None:
        return loaded
    try:
        st = path.stat()
    except OSError:
        return loaded
    stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
    seen = _FRESH.get(path)
    if seen is None or seen["src"] is not got:
        # this config's section was read from the file as it is now
        _FRESH[path] = {"src": got, "stamp": stamp, "values": loaded, "racy": False}
        return dict(loaded)
    if seen["stamp"] != stamp or seen["racy"]:
        seen["stamp"], seen["values"] = stamp, _read(path)
        # read within two seconds of the change: a second write inside the same tick of the
        # filesystem's clock could keep this stamp, so the next call reads it again too
        seen["racy"] = time.time_ns() - st.st_mtime_ns < 2_000_000_000
    return dict(seen["values"])


def _read(path) -> dict:
    import logging

    import yaml

    from ...config import ConfigError
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return parse(raw.get("cubs") if isinstance(raw, dict) else None)
    except (OSError, yaml.YAMLError, ConfigError) as exc:
        logging.getLogger("kranto.core.cubs").warning(
            "the cubs: section of %s does not read (%s): every cub is in practice until it does",
            path, exc)
        return parse({})


def enabled(cfg) -> bool:
    return bool(values(cfg)["cubs.enabled"])


def developer(cfg) -> bool:
    """``cubs.developer``: the cub shop is shown and its verbs offered (off by default)."""
    try:
        return bool(values(cfg).get("cubs.developer", False))
    except Exception:  # noqa: BLE001 - an unreadable section: the shop stays shut
        return False


def cub_value(cfg, cid: str, name: str, *, trust: str = "unreviewed"):
    """One cub's key in force: its own value, else the value of the cub it reads as by id alias
    (``registry.alias_sources``: Kranto's ``blog`` reads the owner's ``examplecom`` settings, read
    and
    never rewritten), else the default (by trust where it has one)."""
    from .registry import alias_sources
    v = values(cfg)
    for one in (cid, *alias_sources(cid)):
        mine = v["per"].get(one) or {}
        if isinstance(mine, dict) and name in mine and mine[name] is not None:
            return mine[name]
    if name == "monthly_usd":
        return None if trust in UNCAPPED_TIERS else v["cubs.default_monthly_usd"]
    if name == "calls_per_day":
        return 10000 if trust in UNCAPPED_TIERS else v["cubs.default_calls_per_day"]
    return _default(PER_CUB[name])


def own_value(cfg, cid: str, name: str):
    """The owner's own value of one cub's key (its own, else its alias's), or None: no
    default."""
    from .registry import alias_sources
    v = values(cfg)
    for one in (cid, *alias_sources(cid)):
        mine = v["per"].get(one) or {}
        if isinstance(mine, dict) and mine.get(name) is not None:
            return mine[name]
    return None


def cub_enabled(cfg, cid: str) -> bool:
    return bool(cub_value(cfg, cid, "enabled"))


def live_kinds(cfg, cid: str) -> list[str]:
    """The kinds live for a cub, each with its other names: a kind turned live under an
    earlier release's name (an alias, ``meta.alias_of``) is live under its own, and the
    other way round, so a cub updated to the neutral names keeps its mode. None on the
    preview: every cub there is in practice, whatever the copied settings say."""
    from ... import preview
    from .. import tickets
    if preview.enabled(getattr(cfg, "root", None)):
        return []
    raw = list(cub_value(cfg, cid, "live") or [])
    tickets.kind_names()
    out = list(raw)
    for kind in tickets.KINDS:
        if kind not in out and any(tickets.same_kind(kind, k) for k in raw):
            out.append(kind)
    return out


def raw_live(cfg, cid: str) -> list[str]:
    """``cubs.<id>.live`` as written."""
    return list(cub_value(cfg, cid, "live") or [])


def limits(cfg, cid: str, trust: str) -> dict:
    """The process limits and the quota in force for one cub."""
    return {n: cub_value(cfg, cid, n, trust=trust)
            for n in ("memory_mb", "pids", "cpu_pct", "tmp_mb", "kv_mb")}


def weak_limits(cfg, trust: str, mode: str) -> str | None:
    """Why a cub of ``trust`` does not start where the limits are ``mode`` (only rlimits: no pids
    cap, no CPU quota), or None. The runtime refuses with it and the install dialog says it
    before the install."""
    if mode != "rlimits" or trust in UNCAPPED_TIERS or values(cfg)["cubs.allow_rlimits"]:
        return None
    return ("this machine cannot cap a cub's processes (no systemd user manager), so only "
            "your own cubs run here; it will not run until cubs.allow_rlimits: true in "
            "kranto.yaml")


def checked(key: str, value, *, trust: str | None = None):
    """``value`` for ``key`` as ``write`` would keep it, or SettingError; writes nothing (the
    verbs' door checks a prepared press with it: PAR)."""
    parts = key.split(".")
    if parts[0] != "cubs" or not all(re.fullmatch(r"[a-z0-9_]+", p) for p in parts):
        raise SettingError(f"{key} is not one of the cubs keys")
    if len(parts) == 2:
        if key not in GLOBAL:
            raise SettingError(f"{key} is not one of the cubs keys")
        return _check_global(key, value)
    if len(parts) == 3 and ID.fullmatch(parts[1]) and parts[1] not in GLOBAL_NAMES:
        return check_per_cub(parts[1], parts[2], value, trust=trust)
    raise SettingError(f"{key} is not one of the cubs keys")


def write(cfg, key: str, value, *, trust: str | None = None) -> dict:
    """Write one ``cubs.*`` key to ``kranto.yaml`` (the file edited as text: comments and order
    stay) and return the section's values as they now are. ``trust``: the cub's, for its
    ceilings. Whether the caller may write it (the page's house confirm for ``cubs.enabled``
    and for adding a live kind) is the API's job."""
    from ... import config as config_mod
    from ...setup import write_config_values

    parts = key.split(".")
    clean = checked(key, value, trust=trust)
    path = config_mod.config_path(cfg.root)
    if path is None:
        raise SettingError("this Kranto has no kranto.yaml")
    write_config_values(path, {tuple(parts): clean})
    now = values(cfg)
    if len(parts) == 2:
        now[key] = clean
    else:
        now["per"] = {**now["per"], parts[1]: {**now["per"].get(parts[1], {}), parts[2]: clean}}
    return now


def outside_range(store, cid: str) -> str | None:
    """Why this host is outside the cub's ``kranto`` range, or None (no range, or inside it).
    A cub outside its range runs dry only."""
    from ... import __version__
    from ..manifest import in_range
    row = store.query_one("SELECT bears_range FROM cubs WHERE cub = ? ORDER BY id DESC LIMIT 1",
                          (cid,))
    rng = row["bears_range"] if row else None
    if not rng or in_range(__version__, rng):
        return None
    return f"Kranto {__version__} is outside its range ({rng})"


def describe(cfg) -> dict:
    """The section for the page and ``GET /api/cubs``: the global keys with their rules and
    values, and each cub's keys as written."""
    v = values(cfg)
    return {"keys": [{"key": k, "value": v[k], "type": r.type, "default": r.default,
                      "lo": r.lo, "hi": r.hi, "words": r.words} for k, r in GLOBAL.items()],
            "per_cub": [{"name": n, "type": r.type, "default": r.default, "lo": r.lo,
                         "hi": r.hi, "words": r.words} for n, r in PER_CUB.items()],
            "cubs": v["per"]}
