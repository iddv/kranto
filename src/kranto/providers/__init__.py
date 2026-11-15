"""Model providers: how the metered client's requests reach a model (``base.py``), and the one
place that finds, tests and chooses them.

Providers: ``openai_compat`` (an OpenAI-style chat completions endpoint), ``openrouter`` (the
same provider under OpenRouter's name and URL), ``anthropic`` (the Claude API's Messages
endpoint) and ``claude_code`` (the user's Claude Code login, an explicit choice only, with
``CLAUDE_CODE_TERMS`` shown where it is chosen). ``make_provider`` builds the one
``LLMClient`` asks for.

``detect``, ``test`` and ``choose`` are what the setup wizard (``kranto setup``), the web
Welcome and Settings › Watching (``GET/POST /api/setup/provider``) and ``python -m kranto
provider`` call; none
of them returns, logs or stores a key.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path

import httpx

from ..config import LLMConfig
from .base import KeyTest, Provider, ProviderError, Reply, Request

__all__ = ["CHOICES", "CLAUDE_CODE_TERMS", "KeyTest", "Provider", "ProviderError", "Reply",
           "Request", "choose", "detect", "make_provider", "test"]

OPENROUTER_URL = "https://openrouter.ai/api/v1"
OPENROUTER_ENV = "OPENROUTER_API_KEY"
ANTHROPIC_ENV = "ANTHROPIC_API_KEY"
# What the wizard and Welcome offer, in the order they offer it when several are found
# (MP D12): an Anthropic key, an OpenRouter key, another endpoint, then Claude Code's login,
# never preselected.
CHOICES = ("anthropic", "openrouter", "openai_compat", "claude_code")
KEY_CHOICES = ("anthropic", "openrouter", "openai_compat")
# Each model under both names: the Claude API's (and Claude Code's) id, and OpenRouter's.
# The same pairs as the page's models.CATALOG.
MODEL_PAIRS = (
    ("claude-haiku-5-5", "anthropic/claude-haiku-5.5"),
    ("claude-sonnet-5-5", "anthropic/claude-sonnet-5.5"),
    ("claude-opus-5-5", "anthropic/claude-opus-5.5"),
    ("claude-fable-5-1", "anthropic/claude-fable-5.1"),
    ("claude-sonnet-5", "anthropic/claude-sonnet-5"),
    ("claude-haiku-4-5-20251001", "anthropic/claude-haiku-4.5"),
)
# The tiers' models on a provider chosen afresh (MP D3): Haiku 5.5 judges, Sonnet 5.5 reasons.
DEFAULT_MODELS = {"judge": "claude-haiku-5-5", "reason": "claude-sonnet-5-5"}
LABELS = {"anthropic": "Claude API", "openrouter": "OpenRouter",
          "openai_compat": "another endpoint", "claude_code": "Claude Code"}
# Said wherever Claude Code's login is chosen: the wizard, Welcome, Settings, the doctor.
from .claude_code import TERMS as CLAUDE_CODE_TERMS  # noqa: E402


def make_provider(name: str, cfg: LLMConfig, *, key: Callable[[str | None], str | None],
                  http: Callable[..., httpx.Client]) -> Provider:
    """The provider ``name`` for ``cfg``. ``key(env)`` reads a key by its variable's name;
    ``http(timeout=, headers=)`` makes the HTTP client it sends with."""
    if name in ("openai_compat", "openrouter"):
        from .openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(
            name=name, base_url=cfg.base_url, key_env=cfg.api_key_env,
            cost_source=cfg.cost_source, key=lambda: key(cfg.api_key_env), http=http())
    if name == "claude_code":
        from .claude_code import ClaudeCodeProvider
        c = cfg.claude_code
        return ClaudeCodeProvider(cwd=c.cwd, home=c.home, structured=c.structured,
                                  sandbox=c.sandbox, timeout=c.timeout_seconds)
    if name == "openai":
        from .openai import KEY_ENV, OpenAIProvider
        return OpenAIProvider(key=lambda: key(KEY_ENV), http=http())  # type: ignore[return-value]
    if name == "xai":
        from .xai import XAIProvider
        return XAIProvider(key=lambda: key("XAI_API_KEY"), http=http())
    if name == "anthropic":
        from .anthropic import AnthropicProvider
        a = cfg.anthropic
        return AnthropicProvider(base_url=a.base_url, key_env=a.api_key_env,
                                 key=lambda: key(a.api_key_env), http=http(), cache=a.cache,
                                 structured=a.structured, effort=a.effort)
    raise ValueError(f"unknown provider '{name}'")


def model_name(model: str, provider: str) -> str:
    """``model`` in ``provider``'s names (OpenRouter's ``anthropic/...`` or the Claude API's
    id); a model not in the pairs is kept as typed."""
    for api_id, router in MODEL_PAIRS:
        if model in (api_id, router):
            return router if provider in ("openrouter", "openai_compat") else api_id
    return model


def models_for(provider: str, llm: LLMConfig) -> dict:
    """Both tiers' models when the watcher moves to ``provider``: today's models when the
    names do not change (OpenRouter and another endpoint share them), else today's models
    under the provider's names, and Haiku 5.5 and Sonnet 5.5 for a model with no pair."""
    names = {"openrouter": "router", "openai_compat": "router"}   # anthropic, claude_code: ids
    current = {t: llm.models[t] for t in ("judge", "reason")}
    if names.get(provider, "id") == names.get(llm.provider_name, "id"):
        return current
    known = {m for pair in MODEL_PAIRS for m in pair}
    return {t: model_name(m if m in known else DEFAULT_MODELS[t], provider)
            for t, m in current.items()}


def in_use(llm: LLMConfig) -> dict:
    """What the metered client (``llm.py``) sends with, from the same ``LLMConfig`` it is
    built from: Settings › Watching, ``kranto doctor`` and ``python -m kranto provider show`` all
    say
    this and nothing else (``llm.base_url`` is only the OpenAI-style endpoint's, kept when
    another provider is chosen)::

        {"provider": "anthropic",       # llm.provider, as llm_calls.provider records it
         "choice": "anthropic",         # as offered: an endpoint at openrouter.ai is openrouter
         "label": "Claude API", "endpoint": "https://api.anthropic.com" | None (Claude Code),
         "key_env": "ANTHROPIC_API_KEY" | None, "models": {"judge": ..., "reason": ...},
         "tiers": {"judge": "anthropic", "reason": "anthropic"}}
    """
    name = llm.provider_name
    choice = "openrouter" if name == "openai_compat" and "openrouter.ai" in llm.base_url \
        else name
    endpoint = {"anthropic": llm.anthropic.base_url, "claude_code": None}.get(name, llm.base_url)
    return {"provider": name, "choice": choice, "label": LABELS.get(choice, choice),
            "endpoint": endpoint, "key_env": llm.key_env,
            "models": {t: llm.model_for(t) for t in ("judge", "reason") if t in llm.models},
            "tiers": {t: llm.provider_for(t) for t in sorted(llm.models)}}


def last_call(store) -> dict | None:
    """The ledger's newest call (``llm_calls``): which provider served it, its model and when;
    None before the first. What ``in_use`` says is checked against it."""
    row = store.query_one("SELECT provider, model, created_at FROM llm_calls "
                          "ORDER BY id DESC LIMIT 1")
    if row is None:
        return None
    return {"provider": row["provider"] or "openai_compat", "model": row["model"],
            "at": row["created_at"]}


def _dotenv_names(root: Path | None) -> set[str]:
    """The variable names set in ``<root>/.env`` (names only; no value is kept)."""
    if root is None or not (root / ".env").is_file():
        return set()
    names = set()
    for line in (root / ".env").read_text(encoding="utf-8").splitlines():
        name, eq, value = line.strip().removeprefix("export ").partition("=")
        if eq and value.strip() and not name.startswith("#"):
            names.add(name.strip())
    return names


def _load(root: Path | None):
    from .. import config as config_mod
    if root is None:
        return None
    try:
        return config_mod.load(root, dotenv=False)
    except config_mod.ConfigError:
        return None


def _claude_code(run) -> dict:
    """Claude Code on PATH, its version and whether it is signed in (``claude auth status``;
    the credentials are never read)."""
    rc, out = run(["claude", "--version"])
    if rc == 127:
        return {"installed": False, "version": None, "logged_in": False,
                "auth_method": None, "subscription": None}
    m = re.search(r"\d+\.\d+\.\d+", out or "")
    rc, out = run(["claude", "auth", "status"])
    try:
        info = json.loads(out[out.index("{"):]) if "{" in (out or "") else {}
    except ValueError:
        info = {}

    def word(v):
        v = str(v or "").strip()
        return v if re.fullmatch(r"[\w.-]{1,40}", v) else None
    return {"installed": True, "version": m.group(0) if m else None,
            "logged_in": bool(rc == 0 and info.get("loggedIn")),
            "auth_method": word(info.get("authMethod")),
            "subscription": word(info.get("subscriptionType"))}


_claude_seen: tuple[float, dict, object] | None = None


def claude_code_kept() -> dict:
    """``_claude_code`` through ``setup.RUN``, its last answer at once and asked again in the
    background once older than ``setup.LOGIN_CACHE_SECONDS`` (SL: Settings › Watching opens
    without waiting on two ``claude`` processes); the first ask waits for it."""
    import time

    from .. import setup

    def ask() -> dict:
        global _claude_seen
        run = setup.RUN
        out = _claude_code(run)
        _claude_seen = (time.monotonic(), out, run)
        return out
    hit = _claude_seen
    if hit and hit[2] is setup.RUN:
        if time.monotonic() - hit[0] >= setup.LOGIN_CACHE_SECONDS:
            setup.again("claude-code", ask)
        return dict(hit[1])
    return dict(ask())


def detect(root: Path | str | None = None, *, environ=None, run=None) -> dict:
    """What can serve the watcher's models on this machine, in ``CHOICES`` order. ``root``:
    the kranto home (its config and ``.env``). Never reads a key's value::

        {"current": {**in_use(llm), "key_set": bool},
         "choices": ["anthropic", "openrouter", "openai_compat"],
         "anthropic": {"key_set": bool, "env": "ANTHROPIC_API_KEY", "label": "Claude API"},
         "openrouter": {"key_set": bool, "env": "OPENROUTER_API_KEY", "label": ...},
         "openai_compat": {"key_set": bool, "env": ..., "base_url": ..., "label": ...},
         "claude_code": {"installed", "version", "logged_in", "auth_method", "subscription",
                         "token_in_service", "offered": False, "label"}}
    """
    root = Path(root) if root is not None else None
    environ = os.environ if environ is None else environ
    claude = _claude_code(run) if run else claude_code_kept()
    cfg = _load(root)
    names = _dotenv_names(root) | {k for k, v in environ.items() if v}
    llm = cfg.llm if cfg else None
    compat_env = llm.api_key_env if llm else OPENROUTER_ENV
    anthropic_env = llm.anthropic.api_key_env if llm else ANTHROPIC_ENV
    compat_url = llm.base_url if llm else OPENROUTER_URL
    on_router = "openrouter.ai" in compat_url
    out = {
        "current": ({**in_use(llm), "key_set": (llm.key_env in names) if llm.key_env else True}
                    if llm else None),
        "choices": list(CHOICES),
        "anthropic": {"key_set": anthropic_env in names, "env": anthropic_env,
                      "label": LABELS["anthropic"]},
        "openrouter": {"key_set": on_router and compat_env in names, "env": compat_env,
                       "label": LABELS["openrouter"]},
        "openai_compat": {"key_set": (not on_router) and compat_env in names,
                          "env": compat_env, "base_url": None if on_router else compat_url,
                          "label": LABELS["openai_compat"]},
        "claude_code": {**claude,
                        "token_in_service": bool(environ.get("CLAUDE_CODE_OAUTH_TOKEN")),
                        "offered": True, "label": LABELS["claude_code"],
                        "terms": CLAUDE_CODE_TERMS},
    }
    return out


def _key_from(env: str, root: Path | None, environ) -> str | None:
    from ..config import load_dotenv
    if root is not None:
        load_dotenv(root / ".env")
    return (environ.get(env) or os.environ.get(env) or "").strip() or None


def test(provider: str, *, key: str | None = None, base_url: str | None = None,
         root: Path | str | None = None, environ=None,
         transport: httpx.BaseTransport | None = None) -> KeyTest:
    """Test ``provider`` with ``key`` (default: the key already set for it), spending nothing:
    OpenRouter ``GET /key``, another endpoint ``GET /models``, the Claude API
    ``GET /v1/models`` (which also says whether the default models are offered). The key is
    scrubbed from every detail."""
    from .. import setup
    root = Path(root) if root is not None else None
    environ = os.environ if environ is None else environ
    cfg = _load(root)
    llm = cfg.llm if cfg else None
    if provider == "anthropic":
        from .anthropic import AnthropicProvider
        env = llm.anthropic.api_key_env if llm else ANTHROPIC_ENV
        key = key or _key_from(env, root, environ)
        url = base_url or (llm.anthropic.base_url if llm else "https://api.anthropic.com")
        p = AnthropicProvider(base_url=url, key_env=env, key=lambda: key,
                              http=httpx.Client(timeout=setup.KEY_TEST_SECONDS,
                                                transport=transport))
        try:
            result = p.test(key)
        finally:
            p.close()
        if result.ok:
            wanted = list(DEFAULT_MODELS.values())
            missing = [m for m in wanted if m not in result.models]
            detail = (f"{result.detail}: {' and '.join(wanted)} are offered" if not missing
                      else f"{result.detail}, but {', '.join(missing)} is not offered to it")
            result = KeyTest(True, detail, result.models)
        return KeyTest(result.ok, setup.scrub_key(result.detail, key or ""), result.models)
    if provider in ("openrouter", "openai_compat"):
        env = llm.api_key_env if llm else OPENROUTER_ENV
        key = key or _key_from(env, root, environ)
        if provider == "openrouter":
            url = OPENROUTER_URL
        else:
            url = base_url or (llm.base_url if llm else None)
            if not url:
                return KeyTest(False, "another endpoint needs its base URL")
        if not key:
            return KeyTest(False, f"${env} is not set")
        r = setup.try_key(url, key, transport=transport)
        return KeyTest(r.ok, setup.scrub_key(r.detail, key))
    if provider == "claude_code":
        return _test_claude_code(environ, setup.RUN)
    return KeyTest(False, f"unknown provider '{provider}'")


def xai_key(root: Path | str, key: str | None = None, *, environ=None,
            transport: httpx.BaseTransport | None = None) -> dict:
    """The xAI key, for X search through Grok only, never a watching
    provider: test ``key`` (default: the one set) with ``GET /v1/models``, spending nothing,
    and only when it passes and was given, write it to ``<root>/.env`` (0600) as
    ``XAI_API_KEY``. Returns ``{"ok", "detail", "changed"}``, never the key."""
    from .. import setup
    from .xai import KEY_ENV, XAIProvider
    root = Path(root)
    environ = os.environ if environ is None else environ
    if key is not None:
        key = setup.check_key_shape(key)
    use = key or _key_from(KEY_ENV, root, environ)
    p = XAIProvider(key=lambda: use, http=httpx.Client(timeout=setup.KEY_TEST_SECONDS,
                                                         transport=transport))
    try:
        result = p.test(use)
    finally:
        p.close()
    out = {"ok": result.ok, "detail": setup.scrub_key(result.detail, use or ""), "changed": False}
    if result.ok and key is not None and (os.environ.get(KEY_ENV) != key
                                          or KEY_ENV not in _dotenv_names(root)):
        setup.write_env_key(root, KEY_ENV, key)
        os.environ[KEY_ENV] = key
        out["changed"] = True
    return out


def openai_key(root: Path | str, key: str | None = None, *, environ=None,
               transport: httpx.BaseTransport | None = None) -> dict:
    """The OpenAI key, for a post writer's own model only (P-11), never the watcher's: test
    ``key`` (default: the one set) with ``GET /v1/models``, spending nothing, and only when it
    passes and was given, write it to ``<root>/.env`` (0600) as ``OPENAI_API_KEY``. Returns
    ``{"ok", "detail", "changed"}``, never the key."""
    from .. import setup
    from .openai import KEY_ENV, OpenAIProvider
    root = Path(root)
    environ = os.environ if environ is None else environ
    if key is not None:
        key = setup.check_key_shape(key)
    use = key or _key_from(KEY_ENV, root, environ)
    p = OpenAIProvider(key=lambda: use, http=httpx.Client(timeout=setup.KEY_TEST_SECONDS,
                                                            transport=transport))
    try:
        result = p.test(use)
    finally:
        p.close()
    out = {"ok": result.ok, "detail": setup.scrub_key(result.detail, use or ""), "changed": False}
    if result.ok and key is not None and (os.environ.get(KEY_ENV) != key
                                          or KEY_ENV not in _dotenv_names(root)):
        setup.write_env_key(root, KEY_ENV, key)
        os.environ[KEY_ENV] = key
        out["changed"] = True
    return out


def _test_claude_code(environ, run) -> KeyTest:
    """Claude Code installed (2.1.300 or newer), signed in or given a token, and a page version
    that can run it as the watcher. Spends nothing (``claude --version``, ``claude auth
    status``)."""
    from .claude_code import MIN_VERSION, version_ok
    cc = _claude_code(run)
    if not cc["installed"]:
        return KeyTest(False, "Claude Code is not installed (no claude on PATH)")
    if not version_ok(cc["version"]):
        return KeyTest(False, f"Claude Code {cc['version'] or '(unknown version)'} is too old: "
                              f"{'.'.join(map(str, MIN_VERSION))} or newer (claude update)")
    token = bool(environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
    if not cc["logged_in"] and not token:
        return KeyTest(False, "Claude Code is not signed in: run 'claude auth login'")
    from .claude_code import host_api
    if host_api() is None:
        return KeyTest(False, "this version of Kranto cannot run Claude Code as the watching model "
                              "(update Kranto)")
    how = ", ".join(x for x in (cc["auth_method"], cc["subscription"]) if x)
    who = "Kranto's CLAUDE_CODE_OAUTH_TOKEN" if token else f"signed in ({how})" if how \
        else "signed in"
    return KeyTest(True, f"Claude Code {cc['version']}, {who}")


def choose(root: Path | str, provider: str, *, key: str | None = None,
           base_url: str | None = None, models: dict | None = None, environ=None,
           transport: httpx.BaseTransport | None = None, terms: bool = False,
           keep_failed: bool = False) -> dict:
    """Make ``provider`` the watcher's: test it (``test``), and only if that passes (or
    ``keep_failed``: the wizard's "keep it anyway", a machine offline at install) write the
    key into ``<root>/.env`` (0600) under the provider's variable, and ``llm.provider``, both
    tiers' models in the provider's names (``models``, else today's models renamed, else
    Haiku 5.5 and Sonnet 5.5) and, for an endpoint, ``llm.base_url`` into the config.
    Re-running with the same answers changes nothing. ``claude_code`` takes no key and needs
    ``terms=True``: the caller showed ``CLAUDE_CODE_TERMS`` where it was chosen (the owner's
    D2). Returns what was written and the test, never the key::

        {"ok": bool, "provider": ..., "models": {...}, "base_url": ... | None, "env": ...,
         "changed": bool, "test": {"ok": bool, "detail": str}}
    """
    from .. import config as config_mod
    from .. import setup
    root = Path(root)
    environ = os.environ if environ is None else environ
    if provider not in CHOICES:
        raise setup.SetupError(f"choose one of {', '.join(CHOICES)}")
    if provider == "claude_code" and not terms:
        raise setup.SetupError("Claude Code is chosen only once its terms were shown: "
                               + CLAUDE_CODE_TERMS)
    if provider == "claude_code" and key is not None:
        raise setup.SetupError("Claude Code takes no key: it uses its own login")
    if key is not None:
        key = setup.check_key_shape(key)
    if provider == "openai_compat" and base_url is not None:
        base_url = setup.check_base_url(base_url)
    cfg = config_mod.load(root, dotenv=False)
    llm = cfg.llm
    result = test(provider, key=key, base_url=base_url, root=root, environ=environ,
                  transport=transport)
    out = {"ok": result.ok, "provider": provider, "env": llm.env_for(provider),
           "test": {"ok": result.ok, "detail": result.detail}, "changed": False,
           "models": None, "base_url": None}
    if not result.ok and not (keep_failed and key is not None):
        return out
    if models:
        chosen = {t: str(models.get(t) or llm.models[t]) for t in ("judge", "reason")}
    else:
        chosen = models_for(provider, llm)
    values: dict[tuple[str, ...], object] = {
        ("llm", "provider"): provider,
        ("llm", "models", "judge"): chosen["judge"],
        ("llm", "models", "reason"): chosen["reason"],
    }
    if provider == "openrouter":
        values[("llm", "base_url")] = OPENROUTER_URL
        out["base_url"] = OPENROUTER_URL
    elif provider == "openai_compat":
        url = base_url or llm.base_url
        values[("llm", "base_url")] = url
        out["base_url"] = url
    path = config_mod.config_path(root)
    before = path.read_text(encoding="utf-8")
    key_changed = False
    if key is not None:
        env = llm.env_for(provider)
        key_changed = os.environ.get(env) != key or env not in _dotenv_names(root)
        if key_changed:
            setup.write_env_key(root, env, key)
            os.environ[env] = key
    setup.write_config_values(path, values)
    out["changed"] = key_changed or path.read_text(encoding="utf-8") != before
    out["models"] = chosen
    return out
