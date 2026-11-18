"""``kranto doctor``: check that an instance can actually run, before it spends."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

from . import library, pricing
from .config import Config
from .llm import pause_words, watch_pause
from .store import Store, iso, month_start, utcnow
from .stored.runs import IngestSummary

OK, WARN, FAIL = "ok", "warn", "FAIL"


@dataclass(frozen=True)
class Check:
    status: str
    name: str
    detail: str


def _models(cfg: Config, transport: httpx.BaseTransport | None) -> Check | list[Check]:
    headers = {}
    if cfg.llm.api_key():
        headers["Authorization"] = f"Bearer {cfg.llm.api_key()}"
    try:
        with httpx.Client(transport=transport, timeout=15) as client:
            response = client.get(f"{cfg.llm.base_url}/models", headers=headers)
    except httpx.HTTPError as exc:
        return Check(FAIL, "provider", f"cannot reach {cfg.llm.base_url}: {exc}")
    if response.status_code != 200:
        return Check(WARN, "provider", f"{cfg.llm.base_url}/models returned "
                                       f"{response.status_code}; model names not checked")
    try:
        available = {m.get("id") for m in response.json().get("data", [])}
    except (ValueError, AttributeError):
        return Check(WARN, "provider", "could not read the model list; names not checked")
    out = []
    for tier, model in sorted(cfg.llm.models.items()):
        if model in available:
            out.append(Check(OK, f"{tier} model", model))
        else:
            out.append(Check(FAIL, f"{tier} model",
                             f"{model} is not offered by {cfg.llm.base_url}"))
    return out


def _key(cfg: Config, transport: httpx.BaseTransport | None) -> Check:
    key = cfg.llm.api_key()
    if not key:
        return Check(FAIL, "api key", f"${cfg.llm.api_key_env} is not set "
                                      f"(shell or {cfg.root / '.env'})")
    if "openrouter.ai" not in cfg.llm.base_url:
        return Check(OK, "api key", f"${cfg.llm.api_key_env} is set (not verified for this "
                                    "provider)")
    try:
        with httpx.Client(transport=transport, timeout=15) as client:
            response = client.get(f"{cfg.llm.base_url}/key",
                                  headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        return Check(WARN, "api key", f"could not verify: {exc}")
    if response.status_code in (401, 403):
        return Check(FAIL, "api key", f"rejected by OpenRouter (HTTP {response.status_code})")
    if response.status_code != 200:
        return Check(WARN, "api key", f"could not verify (HTTP {response.status_code})")
    data = response.json().get("data", {})
    remaining = data.get("limit_remaining")
    detail = "accepted by OpenRouter"
    if remaining is not None:
        detail += f"; ${float(remaining):.2f} of key limit remaining"
    return Check(OK, "api key", detail)


def _anthropic(cfg: Config, transport: httpx.BaseTransport | None) -> list[Check]:
    """The Claude API: the key tested with ``GET /v1/models`` (free), and each tier on it
    offered to the key."""
    from . import providers
    env = cfg.llm.anthropic.api_key_env
    if not os.environ.get(env):
        return [Check(FAIL, "api key", f"${env} is not set (shell or {cfg.root / '.env'})")]
    result = providers.test("anthropic", root=cfg.root, transport=transport)
    if not result.ok:
        return [Check(FAIL, "api key", result.detail)]
    out = [Check(OK, "api key", f"${env}: the Claude API accepted the key")]
    for tier in sorted(cfg.llm.models):
        if cfg.llm.provider_for(tier) != "anthropic":
            continue
        model = cfg.llm.model_for(tier)
        out.append(Check(OK, f"{tier} model", model) if model in result.models else
                   Check(FAIL, f"{tier} model", f"{model} is not offered to this key"))
    return out


def _prices(cfg: Config) -> Check:
    """The models priced from Kranto's table (the Claude API's) have a price, and the table is
    not old."""
    tiers = [t for t in sorted(cfg.llm.models) if cfg.llm.provider_for(t) == "anthropic"]
    missing = [cfg.llm.model_for(t) for t in tiers
               if pricing.price_for(cfg.llm.model_for(t), cfg.llm.pricing) is None]
    if missing:
        return Check(FAIL, "pricing", f"no price for {', '.join(missing)}: its calls are "
                                      "refused (add it under llm.pricing)")
    if pricing.stale():
        return Check(WARN, "pricing", f"prices in pricing.py are from {pricing.PRICES_AS_OF}; "
                                      "check Anthropic's pricing page and update Kranto")
    return Check(OK, "pricing", f"Claude API list prices of {pricing.PRICES_AS_OF}, cache "
                                "reads and writes included")


def _compat(cfg: Config, transport: httpx.BaseTransport | None) -> list[Check]:
    """An OpenAI-style endpoint (OpenRouter or another): its key, its models, its prices."""
    checks = [_key(cfg, transport)]
    models = _models(cfg, transport)
    checks += models if isinstance(models, list) else [models]
    if cfg.llm.cost_source == "table":
        missing = [m for m in cfg.llm.models.values() if m not in cfg.llm.pricing]
        checks.append(Check(FAIL if missing else OK, "pricing",
                            f"no price for {', '.join(missing)}" if missing
                            else "every model has a price"))
    elif "openrouter.ai" not in cfg.llm.base_url:
        checks.append(Check(WARN, "pricing", "cost_source is 'provider' but the provider may "
                                             "not report costs; calls will be refused if not"))
    return checks


def _claude_code(cfg: Config, store: Store) -> list[Check]:
    """Claude Code's login as the watching model: installed, signed in, a page version that can run
    it; what this month used at list prices; and what choosing it means."""
    from . import providers
    result = providers.test("claude_code")
    out = [Check(OK if result.ok else FAIL, "claude login", result.detail)]
    row = store.query_one("SELECT COUNT(*) AS n, COALESCE(SUM(equiv_usd), 0) AS usd FROM "
                          "llm_calls WHERE provider = 'claude_code' AND created_at >= ?",
                          (iso(month_start(utcnow())),))
    assert row is not None                     # an aggregate always answers one row
    out.append(Check(OK, "plan usage", f"{row['n']} calls this month, about ${row['usd']:.2f} "
                                       f"at API list prices, billed to your plan, not in dollars. "
                                       f"{providers.CLAUDE_CODE_TERMS}"))
    return out


def provider_line(cfg: Config) -> Check:
    """Which provider serves the tiers: what the metered client sends with
    (``providers.in_use``, the same words as Settings › Watching and ``kranto watch provider
    show``)."""
    from .providers import LABELS, in_use
    use = in_use(cfg.llm)
    names = cfg.llm.providers_in_use()
    parts = []
    for name in names:
        tiers = [t for t in sorted(cfg.llm.models) if cfg.llm.provider_for(t) == name]
        label = use["label"] if name == use["provider"] else LABELS.get(name, name)
        parts.append(f"{label} ({name})"
                     + (f" for {', '.join(tiers)}" if len(names) > 1 else ""))
    return Check(OK, "provider", "; ".join(parts))


def ledger_line(cfg: Config, store: Store) -> Check | None:
    """The ledger's newest call against the provider the config names: the same after a call
    on the current provider; just after a change, the next call goes to the new one."""
    from .providers import last_call
    last = last_call(store)
    if last is None:
        return None
    served = last["provider"]
    if served in cfg.llm.providers_in_use():
        return Check(OK, "last call", f"{served} ({last['model']}) at {last['at']}")
    return Check(OK, "last call", f"{served} ({last['model']}) at {last['at']}, before the "
                                  f"change: the next call goes to {cfg.llm.provider_name}")


def watch_login(cfg: Config, service_names: set[str]) -> Check | None:
    """Which login the console uses when an Anthropic key is about (MP D5). The page hands
    every ``claude`` it starts ``CLAUDE_CODE_OAUTH_TOKEN`` if Kranto has one, else
    ``ANTHROPIC_API_KEY``: with the key and no token, the console bills the key too.
    ``service_names``: the variables Kranto's service has (names only); its ``.env`` is added."""
    from . import providers
    names = set(service_names) | providers._dotenv_names(cfg.root)
    env = cfg.llm.anthropic.api_key_env
    watcher = "anthropic" in cfg.llm.providers_in_use()
    label, who = "claude login", "the console"
    if "ANTHROPIC_API_KEY" not in names:
        if watcher and env in names:
            return Check(OK, label, f"the watcher's key is ${env}; {who} uses your "
                                    "Claude login")
        return None
    uses = ("the watcher uses it too" if watcher and env == "ANTHROPIC_API_KEY"
            else "the watcher does not use it")
    if "CLAUDE_CODE_OAUTH_TOKEN" in names:
        return Check(OK, label, f"{who} uses CLAUDE_CODE_OAUTH_TOKEN (your Claude plan); "
                                f"ANTHROPIC_API_KEY is set and {uses}")
    return Check(WARN, label, f"{who} bills ANTHROPIC_API_KEY ({uses}): Kranto has no "
                              "CLAUDE_CODE_OAUTH_TOKEN, and every claude it starts "
                              f"then uses the key. To keep {who} on your Claude plan, "
                              "run 'claude setup-token' and give Kranto "
                              "CLAUDE_CODE_OAUTH_TOKEN")


BUILDS_RETIRED = "this feature is not part of Kranto any more; its settings are ignored"


def retired_builds(cfg: Config) -> list[Check]:
    """One line when the settings still turn builds on (``builds.enabled: true``): builds left
    Kranto, so the section is read and ignored."""
    # Until ``builds`` joins config.RETIRED. Once it does, the loader leaves the section unread,
    # builds.enabled reads false here, and retired_sections says the one line instead: never both.
    from .config import RETIRED
    if "builds" in RETIRED:
        return []
    return [Check(WARN, "builds", BUILDS_RETIRED)] if cfg.builds.enabled is True else []


def _connections(cfg: Config, store: Store,
                 machine_id: Path | None = None) -> list[Check]:
    """The secrets directory's modes and decryption, and connections that need login."""
    from .connections import Connections
    from .sources import HTTP

    conns = Connections(store, cfg.data_dir, HTTP(), enabled=cfg.connections.enabled,
                        machine_id=machine_id,
                        github_client_id=cfg.connections.github_client_id)
    try:
        accounts = conns.accounts()
        reason = conns.unavailable()
        if reason:
            return [Check(WARN if accounts else OK, "connections",
                          f"off: {reason}" + (f"; {len(accounts)} connected accounts cannot be "
                                              "used" if accounts else ""))]
        out = []
        problems = conns.vault.problems()
        old = (" (written before the rename; Kranto rewrites it at the next change)"
               if conns.vault.old_labels else "")
        out.append(Check(FAIL if problems else OK, "secrets",
                         "; ".join(problems) if problems else
                         f"{conns.vault.directory}: 0700, files 0600, readable here{old}"
                         if conns.vault.directory.exists() else "no connected accounts yet"))
        needing = [a for a in accounts if a["state"] == "needs_login"]
        if needing:
            out.append(Check(WARN, "connections", "needs login: " + ", ".join(
                f"{a['provider_name']} {a['account']}" for a in needing)
                + "; reconnect under Settings › Sources › Accounts"))
        elif accounts:
            out.append(Check(OK, "connections", ", ".join(
                f"{a['provider_name']} {a['account']}" for a in accounts)))
        return out
    finally:
        conns.http.close()


def _x_spend(cfg: Config, store: Store) -> list[Check]:
    """``x spend``: this month's X reads and the cap, once there is an X source or a read;
    a warning when X refused the last fetch for credits or the cap holds X sources back."""
    from . import spend

    has_x = store.query_one("SELECT 1 FROM sources WHERE kind = 'x' LIMIT 1") is not None
    month = spend.month(store, "x")
    if not has_x and not month["requests"]:
        return []
    cap = cfg.x.monthly_usd
    detail = (f"${month['usd']:.2f} this month ({month['reads']} reads, an estimate at X's list "
              f"price; the Developer Console is the bill), "
              + (f"cap ${cap:.2f}" if cap is not None else "no cap"))
    last = store.query_one(
        "SELECT f.error FROM source_fetches f JOIN sources s ON s.id = f.source_id "
        "WHERE s.kind = 'x' ORDER BY f.id DESC LIMIT 1")
    error = str(last["error"] or "") if last else ""
    if "credits exhausted" in error:
        return [Check(WARN, "x spend", detail + "; X refused the last fetch: credits exhausted, "
                                                "add credits in the Developer Console")]
    if spend.capped(store, cap) is not None:
        return [Check(WARN, "x spend", detail + "; the cap is reached: X sources wait until "
                                                "the first of next month")]
    return [Check(OK, "x spend", detail)]


def search_line(cfg: Config, store: Store) -> Check:
    """Live search: which backends answer the scout, cards and the editor,
    this month's searches, and a warning when one failed three times in a row. No request."""
    from . import spend, websearch

    s = websearch.searcher(cfg, store)
    state = s.state()
    try:
        if state["web"] is None and not state["free"]:
            return Check(WARN, "search", f"none configured: every caller says "
                                         f"'{websearch.NO_SEARCH}' (kranto setup search)")
        names = ([state["web_label"]] if state["web"] else []) + \
            [websearch.LABELS[b] for b in state["free"]]
        month = {p: spend.month(store, p) for p in set(websearch.SPEND_PROVIDER.values())}
        count = sum(m["requests"] for m in month.values())
        usd = sum(month[p]["usd"] for p in websearch.PAID_PROVIDERS)
        detail = (f"{', '.join(names)}; {count} searches this month, ${usd:.2f}, "
                  + (f"cap ${cfg.search.monthly_usd:.2f}" if cfg.search.monthly_usd is not None
                     else "no cap"))
        off = [c for c, v in cfg.search.callers.items() if v == "off"]
        if off:
            detail += f"; off for {', '.join(off)}"
        failing = state["failing"]
        if failing:
            worst = ", ".join(f"{websearch.LABELS.get(b, b)} failed {n} times in a row"
                              for b, n in failing.items())
            hint = (" (Exa's free mode is rate-limited: add EXA_API_KEY, a free Exa account, or "
                    "choose another provider)" if "exa" in failing and state["free_mode"] else "")
            return Check(WARN, "search", f"{detail}; {worst}{hint}")
        return Check(OK, "search", detail)
    finally:
        http = cast(Any, s.http)               # sources.HTTP (websearch keeps it as object)
        if http is not None:
            http.close()


# keys a release retired: still accepted in kranto.yaml (never an error), never read; the doctor
# says so, so a value set there is not taken for one that works
RETIRED = {"invest.live": "paper-first is retired (one account since 0.6): no longer read",
           "radar.watch": "every topic feeds Invest and the radar: no longer read"}


def retired_keys(cfg: Config) -> list[Check]:
    """A warning per retired key kranto.yaml sets to other than its default (the parsed
    sections hold every key, the defaults filled in)."""
    from .core import registry
    out = []
    for f in registry.features():
        section = (getattr(cfg, "features", None) or {}).get(f.id) or {}
        for key, rule in f.settings.keys.items():
            why = next((w for old, w in RETIRED.items()
                        if key == old or key.startswith(old + ".")), None)
            if why and key in section and section[key] != rule.default:
                out.append(Check(WARN, "settings", f"{key} is set in kranto.yaml: {why}"))
    return out


def retired_sections(cfg: Config) -> list[Check]:
    """One line per section of a feature that left Kranto (``config.RETIRED``) the file still
    holds: it loads, the section is ignored, the data is in its tables and the archive."""
    from .config import RETIRED
    where = cfg.root / "archive"
    return [Check(OK, name, f"{RETIRED[name]} is not part of Kranto any more: its settings are "
                            f"ignored, and its data is kept (kranto archive writes it to {where})")
            for name in getattr(cfg, "retired", ()) if name in RETIRED]


def not_chosen(cfg: Config, store: Store) -> bool:
    """No model chosen yet: setup not done, no Claude Code login chosen, and no key for any
    provider the config names (the page's "Not chosen yet")."""
    from .setup import DONE
    if store.get_setting(DONE):
        return False
    in_use = cfg.llm.providers_in_use()
    if "claude_code" in in_use:
        return False
    if "anthropic" in in_use and os.environ.get(cfg.llm.anthropic.api_key_env):
        return False
    return not cfg.llm.api_key()


def run(cfg: Config, store: Store, *, transport: httpx.BaseTransport | None = None,
        check_embedder: bool = True) -> list[Check]:
    checks: list[Check] = [Check(OK, "workspace", str(cfg.root))]
    missing = store.missing_tables()
    if missing:  # opening recreates triggers, but not a dropped table
        checks.append(Check(FAIL, "library", f"tables missing: {', '.join(missing)}; the "
                            "database was altered outside the server. Restore from a backup."))
    else:
        counted = store.query_one("SELECT COUNT(*) n FROM observations")
        assert counted is not None             # COUNT(*) always answers one row
        checks.append(Check(OK, "library", f"schema v{store.schema_version()}, "
                            f"{counted['n']} observations"))
    in_use = cfg.llm.providers_in_use()
    if not_chosen(cfg, store):
        # a fresh install before Welcome's model step: the default provider is nobody's choice,
        # so its missing key is not a failure (Welcome: "Kranto reads nothing until a model is
        # chosen")
        checks.append(Check(WARN, "model", "none chosen yet: Welcome's first step (Which model "
                                           "reads for you?) chooses one; Kranto reads nothing "
                                           "until then"))
        in_use = []
    else:
        checks.append(provider_line(cfg))
    ledger = ledger_line(cfg, store)
    if ledger is not None:
        checks.append(ledger)
    if "anthropic" in in_use:
        checks += _anthropic(cfg, transport)
        checks.append(_prices(cfg))
    if set(in_use) & {"openai_compat", "openrouter"}:
        checks += _compat(cfg, transport)
    if "claude_code" in in_use:
        checks += _claude_code(cfg, store)
    spent = store.month_spend()
    paused = store.pause_reason()
    checks.append(Check(WARN if paused else OK, "spend",
                        f"${spent:.4f} {cfg.budget.of()} this month"
                        + (f"; paused: {paused}" if paused else "")))
    provider_pause = watch_pause(store)
    if provider_pause:
        checks.append(Check(WARN, "provider", pause_words(provider_pause)))
    approved = library.list_sources(store, "approved")
    # the owner's topics, as the page counts them (B, Gemini 6: "153 approved for 15 topics"
    # while the page and kranto status said 5; ten were builds' project topics)
    topics = [t for t in library.active_topics(store) if t.kind != "project"]
    checks.append(Check(OK if approved else WARN, "sources",
                        f"{len(approved)} approved for {len(topics)} topics"
                        if approved else "none approved; add a topic or a pack"))
    last = store.query_one("SELECT status, error, summary FROM runs WHERE kind = 'ingest' "
                           "ORDER BY finished_at DESC LIMIT 1")
    if last:
        failing = [s.label or f"source {s.source_id}"
                   for s in IngestSummary.load(last["summary"]).sources
                   if s.fetch_error]
        status = {"ok": OK, "degraded": WARN, "skipped": WARN}.get(last["status"], FAIL)
        detail = f"last ingest {last['status']}" + (f": {last['error']}" if last["error"] else "")
        if failing:
            detail += f"; fetch errors: {', '.join(failing[:5])}"
        checks.append(Check(status, "ingest", detail))
    checks += _connections(cfg, store)
    checks += retired_keys(cfg)
    checks += retired_sections(cfg)
    checks += retired_builds(cfg)
    checks += _x_spend(cfg, store)
    checks.append(search_line(cfg, store))
    from .core.cubs import status as cubs_status

    checks += [Check(s, name, detail) for s, name, detail in cubs_status.doctor(cfg, store)]
    from .delivery import describe

    notify_state = describe(cfg)
    checks.append(Check(WARN if notify_state.startswith("not sending") else OK, "notify",
                        notify_state))
    if check_embedder:
        try:
            from .embed import NomicEmbedder

            NomicEmbedder().embed_query("doctor")
            checks.append(Check(OK, "embedder", "nomic-embed-text-v1.5 loads"))
        except Exception as exc:  # the check exists to report any failure here
            checks.append(Check(FAIL, "embedder", f"{type(exc).__name__}: {exc}"))
    return checks
