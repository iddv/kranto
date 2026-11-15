"""Choosing live search's backend: what is configured and set, a test that
spends one search, and the choice written, as ``providers.detect/test/choose`` do for the
watching model. Used by Settings (``GET/POST /api/setup/search``) and ``kranto setup search``.

Keys go into the home's ``.env`` (0600) under ``EXA_API_KEY``, ``BRAVE_API_KEY`` or
``TAVILY_API_KEY`` (``setup.write_env_key``); the choice into ``search.provider``. Nothing here
returns or logs a key: ``detect`` names the variables that are set, never their values."""

from __future__ import annotations

import os
from pathlib import Path

from . import KEY_ENV, LABELS, NO_SEARCH, SPEND_PROVIDER, BackendError, searcher

CHOICES = ("exa", "brave", "tavily", "anthropic", "none")
CHOICE_LABELS = {"exa": "Exa", "brave": "Brave Search", "tavily": "Tavily",
                 "anthropic": "Anthropic web search (the watcher's Claude API key)",
                 "none": "None: no live search"}
FREE_MODE_WORDS = ("Exa's free mode: rate-limited, no account; add a key from a free Exa account "
                   "($10 of credit a month) for your own limits")
TEST_QUERY = "Kranto live search test"


def _dotenv_names(root: Path | None) -> set[str]:
    from ..providers import _dotenv_names as names
    return names(root)


def detect(cfg, store, *, environ=None) -> dict:
    """The state Settings and the wizard show: the provider and its label, which keys are set
    (by name), the free backends, the callers' switches, this month's searches per backend,
    the cap, and the sentence when nothing searches."""
    from .. import spend
    env = os.environ if environ is None else environ
    names = _dotenv_names(cfg.root) | {k for k in KEY_ENV.values() if env.get(k)}
    s = searcher(cfg, store, environ=env)
    try:
        state = s.state()
    finally:
        s.http.close()
    month = {}
    for backend, provider in SPEND_PROVIDER.items():
        m = spend.month(store, provider)
        if m["requests"]:
            month[backend] = {"label": LABELS.get(backend, backend), **m}
    return {**state,
            "choices": [{"provider": c, "label": CHOICE_LABELS[c],
                         "key_env": KEY_ENV.get(c), "key_set": KEY_ENV.get(c) in names
                         if c in KEY_ENV else None} for c in CHOICES],
            "free_mode_words": FREE_MODE_WORDS if state["free_mode"] else None,
            "recent_weeks": cfg.search.recent_weeks, "cache_hours": cfg.search.cache_hours,
            "month": month, "no_search": NO_SEARCH}


def test(cfg, provider: str, *, key: str | None = None, environ=None, http=None,
         store=None) -> dict:
    """One search on ``provider`` (with ``key`` when given, else the one set): ``{"ok",
    "detail", "results"}``. Exa without a key tests its free mode. Free: Exa's free mode;
    otherwise it costs one search, counted in ``api_spend`` when ``store`` is given."""
    from dataclasses import replace
    if provider not in CHOICES:
        raise ValueError(f"choose one of {', '.join(CHOICES)}")
    if provider == "none":
        return {"ok": True, "detail": f"no live search: every caller says '{NO_SEARCH}'",
                "results": 0}
    env = dict(os.environ if environ is None else environ)
    if key is not None and provider in KEY_ENV:
        env[KEY_ENV[provider]] = key
    scfg = replace(cfg.search, provider=provider, free=False, cache_hours=0)
    s = searcher(replace(cfg, search=scfg), store, http, environ=env, caller="owner")
    try:
        backend = s.backends.get(provider)
        if backend is None:
            return {"ok": False, "detail": f"{CHOICE_LABELS[provider]} is not available here",
                    "results": 0}
        try:
            hits = backend.search(TEST_QUERY, None, 3)
        except BackendError as exc:
            return {"ok": False, "detail": f"{s.label(provider)}: {exc}", "results": 0}
        if store is not None:
            s._record(provider)
        dated = sum(1 for h in hits if h.date)
        return {"ok": True, "detail": f"{s.label(provider)} answered: {len(hits)} results, "
                                      f"{dated} dated", "results": len(hits)}
    finally:
        if http is None:
            s.http.close()


def choose(root: Path | str, provider: str, *, key: str | None = None, environ=None,
           http=None, keep_failed: bool = False) -> dict:
    """Make ``provider`` live search's: test it, and only if that passes (or ``keep_failed``:
    the wizard's "keep it anyway", a machine offline at install) write ``key`` (when given) into
    ``<root>/.env`` under its variable and ``search.provider`` into the config. Returns ``{"ok",
    "provider", "env", "changed", "test"}``, never the key."""
    from .. import config as config_mod
    from .. import setup
    root = Path(root)
    if provider not in CHOICES:
        raise setup.SetupError(f"choose one of {', '.join(CHOICES)}")
    if key is not None:
        if provider not in KEY_ENV:
            raise setup.SetupError(f"{CHOICE_LABELS[provider]} takes no key here")
        key = setup.check_key_shape(key)
    cfg = config_mod.load(root, dotenv=False)
    result = test(cfg, provider, key=key, environ=environ, http=http)
    env = KEY_ENV.get(provider)
    out = {"ok": result["ok"], "provider": provider, "env": env, "changed": False,
           "test": {"ok": result["ok"], "detail": result["detail"]}}
    if not result["ok"] and not keep_failed:
        return out
    path = config_mod.config_path(root)
    before = path.read_text(encoding="utf-8")
    changed = False
    if key is not None and env:
        changed = os.environ.get(env) != key or env not in _dotenv_names(root)
        if changed:
            setup.write_env_key(root, env, key)
            os.environ[env] = key
    setup.write_config_values(path, {("search", "provider"): provider})
    out["changed"] = changed or path.read_text(encoding="utf-8") != before
    return out


def set_callers(root: Path | str, callers: dict | None = None,
                recent_weeks: int | None = None) -> None:
    """Write ``search.callers.<name>`` and ``search.recent_weeks`` (checked by the config's
    own parser before anything is written)."""
    from .. import config as config_mod
    from .. import setup
    root = Path(root)
    values: dict = {}
    for name, value in (callers or {}).items():
        values[("search", "callers", name)] = value
    if recent_weeks is not None:
        values[("search", "recent_weeks")] = recent_weeks
    if not values:
        return
    check = {"callers": dict(callers or {}),
             **({"recent_weeks": recent_weeks} if recent_weeks is not None else {})}
    try:
        config_mod.parse_search(check)
    except config_mod.ConfigError as exc:
        raise setup.SetupError(str(exc)) from exc
    setup.write_config_values(config_mod.config_path(root), values)
