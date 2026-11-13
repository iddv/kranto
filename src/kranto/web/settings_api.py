"""The watcher's models and spend caps over HTTP, for Kranto UI's Settings › Watching and
Settings › Spend.

| Method and path            | Does                                                          |
|----------------------------|---------------------------------------------------------------|
| GET  /api/settings/models  | the two model tiers: what each does, the model it is set to;  |
|                            | the provider the client uses (providers.in_use) and the       |
|                            | ledger's last call                                            |
| POST /api/settings/models  | {role, model, gate}: write ``llm.models.<role>`` (and, for the |
|                            | judge, ``ingest.signal_threshold``), used from the next call  |
| GET  /api/settings/spend   | watching's monthly cap (null: none), this month's spend, the    |
|                            | deep dives' daily slice, calls billed to a plan (Claude       |
|                            | Code's login) with their list-price equivalent, and X's reads |
| POST /api/settings/spend   | {monthly_usd, deep_dive_daily_usd, x_monthly_usd,             |
|                            | search_monthly_usd}: any of them, a number of USD or null    |
|                            | (no cap)                                                      |
| GET  /api/settings/reading | how often sources are read and whether deep dives run         |
| POST /api/settings/reading | {every_hours, deep_dive_enabled}: either; every_hours applies |
|                            | after a restart (the jobs take it when they start), deep      |
|                            | dives from the next run                                       |

The YAML is edited as text (``setup.write_config_values``), so its comments survive, and the
running server takes the new values at once: the jobs read the runtime's config when they
run, and the metered client is given the new models and budget. The list of models to choose
from is not here: it is the page's (``kranto.page.models``), the page that shows it. A model is
any name the endpoint knows, routed (``anthropic/claude-haiku-5.5`` on OpenRouter) or not.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import config as config_mod
from .. import providers, setup

# What each tier is used for (the calls are ``llm_calls.purpose``; the limits are
# ``config.MAX_TOKENS``' names).
ROLES = {
    "judge": {"name": "Judge",
              "does": "Screens and judges every item that passes the prefilter, names map "
                      "clusters and writes the weekly rollups. Runs hundreds of times a day.",
              "calls": ["screen", "judge", "deep_dive", "name", "rollup"],
              "limits": ["screen", "judge", "judge_gathered", "name", "rollup"]},
    "reason": {"name": "Reasoner",
               "does": "Scouts sources for a topic, resolves a pasted list of sources, "
                       "explains a neighbourhood, writes idea cards and checks their "
                       "citations. A few calls a day.",
               "calls": ["scout", "resolve", "explain", "card", "verify"],
               "limits": ["scout", "resolve", "explain", "card", "verify"]},
}
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,119}")
MAX_USD = 1_000_000
# how often sources are read: from every half hour to once a week
EVERY_HOURS = (0.5, 168)
# Shown with the judge: a judge model's ratings have their own scale, so the gate goes with it.
GATE_NOTE = ("The gate is the signal an item needs to be kept. Judges rate on their own scales: "
             "on 160 live items (2026-10-08) Haiku 5.5's signals were about a quarter of Haiku "
             "4.5's, and a gate of 0.03 matched 4.5's keeps at 0.20 best (86% of items, against "
             "4.5's own 90% from one run to the next). Change the two together.")


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def usd_or_none(value, what: str) -> float | None:
    """A cap from a request: None (no cap) or a finite number of USD, 0 or more."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or \
            not math.isfinite(value) or not 0 <= value <= MAX_USD:
        raise setup.SetupError(f"{what} must be a number of USD, 0 or more, or null (no cap)")
    return round(float(value), 2)


class SettingsAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def rt(self):
        return self.app.rt

    async def _body(self, request: Request):
        from .app import MAX_JSON_BYTES, _json_body

        body = await _json_body(request)
        if body is None:
            return None, _error(f"expected a JSON object under {MAX_JSON_BYTES} bytes")
        return body, None

    def _path(self):
        path = config_mod.config_path(self.rt.cfg.root)
        if path is None:
            raise setup.SetupError("no config file to write")
        return path

    # -- models -----------------------------------------------------------------------------

    def _models(self) -> dict:
        cfg = self.rt.cfg
        limits = {k: cfg.llm.max_tokens.get(k, v) for k, v in config_mod.MAX_TOKENS.items()}
        roles = [{"role": key, "name": meta["name"], "does": meta["does"],
                  "calls": meta["calls"], "model": cfg.llm.models.get(key),
                  "max_tokens": {c: limits[c] for c in meta["limits"]}}
                 for key, meta in ROLES.items()]
        roles[0].update(gate=cfg.ingest.signal_threshold, gate_note=GATE_NOTE)
        # what the metered client sends with (providers.in_use), never llm.base_url alone: that
        # is the OpenAI-style endpoint's and stays OpenRouter's when the Claude API is chosen
        use = providers.in_use(cfg.llm)
        return {"roles": roles, "base_url": use["endpoint"] or use["label"],
                "provider": use["provider"], "choice": use["choice"], "label": use["label"],
                "endpoint": use["endpoint"], "last_call": providers.last_call(self.rt.store),
                "routed": use["choice"] in ("openrouter", "openai_compat")
                and any("/" in m for m in cfg.llm.models.values()),
                "config": self._path().name}

    async def models(self, request: Request):
        try:
            return JSONResponse(await run_in_threadpool(self._models))
        except setup.SetupError as exc:
            return _error(str(exc), 500)

    def _set_model(self, role: str, model: str, gate: float | None = None) -> dict:
        writes = {("llm", "models", role): model}
        if gate is not None:
            writes[("ingest", "signal_threshold")] = gate
        setup.write_config_values(self._path(), writes)
        cfg = self.rt.cfg
        llm_cfg = replace(cfg.llm, models={**cfg.llm.models, role: model})
        cfg = replace(cfg, llm=llm_cfg)
        if gate is not None:
            cfg = replace(cfg, ingest=replace(cfg.ingest, signal_threshold=gate))
        self.rt.cfg = cfg
        self.rt.llm.config = llm_cfg
        return self._models()

    async def set_model(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        role, model = str(body.get("role") or ""), str(body.get("model") or "").strip()
        if role not in ROLES:
            return _error(f"no such role: {role or '(none)'} (judge or reason)")
        if not MODEL_NAME.fullmatch(model):
            return _error("a model is a name such as anthropic/claude-haiku-5.5 or "
                          "claude-haiku-5-5")
        gate = body.get("gate")
        if gate is not None and (role != "judge" or isinstance(gate, bool)
                                 or not isinstance(gate, int | float)
                                 or not math.isfinite(gate) or not 0 < gate <= 1):
            return _error("the gate is the judge's: a signal above 0 and at most 1")
        try:
            return JSONResponse(await run_in_threadpool(
                self._set_model, role, model, None if gate is None else float(gate)))
        except (OSError, setup.SetupError, config_mod.ConfigError) as exc:
            return _error(f"could not save: {exc}", 500)

    # -- spend ------------------------------------------------------------------------------

    def _spend(self) -> dict:
        cfg, store = self.rt.cfg, self.rt.store
        spent = store.month_spend()
        from .. import spend
        from ..pricing import X_PRICES_AS_OF

        x = spend.month(store, "x")
        conns = self.rt.connections
        connected = conns is not None and any(a["provider"] == "x" for a in conns.accounts())
        return {"monthly_usd": cfg.budget.monthly_usd, "alarm_fraction": cfg.budget.alarm_fraction,
                "spent_usd": round(spent, 6), "alarm": cfg.budget.alarm(spent),
                "deep_dive": {"enabled": cfg.deep_dive.enabled,
                              "daily_usd": cfg.deep_dive.daily_usd},
                "provider": cfg.llm.provider_name, "plan": self._plan(store),
                # X's reads: an estimate at list price, not model spend
                "x": {"monthly_usd": cfg.x.monthly_usd, "spent_usd": x["usd"],
                      "reads": x["reads"], "requests": x["requests"],
                      "capped": spend.capped(store, cfg.x.monthly_usd) is not None,
                      "connected": connected, "prices_as_of": X_PRICES_AS_OF},
                "search": self._search(store),
                "config": self._path().name}

    def _search(self, store) -> dict:
        """Live search this month: one line per backend used, the free ones at
        0, and the cap (``search.monthly_usd``; null: no cap)."""
        from .. import spend, websearch
        from ..pricing import SEARCH_PRICES_AS_OF
        from ..store import iso, month_start, utcnow
        cfg = self.rt.cfg
        lines = []
        for backend, provider in websearch.SPEND_PROVIDER.items():
            m = spend.month(store, provider)
            if not m["requests"]:
                continue
            free = store.query_one(
                "SELECT COUNT(*) AS n FROM api_spend WHERE provider = ? AND kind = "
                "'search_free' AND created_at >= ?",
                (provider, iso(month_start(utcnow()))))["n"]
            lines.append({"backend": backend,
                          "label": websearch.EXA_FREE_LABEL if free and free == m["requests"]
                          else websearch.LABELS.get(backend, backend),
                          "searches": m["requests"], "usd": m["usd"],
                          "free": m["usd"] == 0})
        paid = sum(x["usd"] for x in lines)
        return {"monthly_usd": cfg.search.monthly_usd, "spent_usd": round(paid, 6),
                "capped": cfg.search.monthly_usd is not None and
                paid >= cfg.search.monthly_usd,
                "lines": lines, "prices_as_of": SEARCH_PRICES_AS_OF}

    def _plan(self, store) -> dict | None:
        """This month's calls billed to a plan (cost_usd 0, MP D10): how many, what they would
        have cost at API list prices, and the last usage window that closed."""
        from ..store import iso, month_start, utcnow
        row = store.query_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(equiv_usd), 0) AS usd FROM llm_calls "
            "WHERE equiv_usd IS NOT NULL AND created_at >= ?", (iso(month_start(utcnow())),))
        if not row["n"]:
            return None
        pause = store.query_one(
            "SELECT created_at, error FROM llm_calls WHERE provider = 'claude_code' AND "
            "error LIKE '%usage limit%' ORDER BY id DESC LIMIT 1")
        return {"calls": int(row["n"]), "equiv_usd": round(float(row["usd"]), 6),
                "last_limit_at": pause["created_at"] if pause else None}

    async def spend(self, request: Request):
        try:
            return JSONResponse(await run_in_threadpool(self._spend))
        except setup.SetupError as exc:
            return _error(str(exc), 500)

    def _set_spend(self, values: dict) -> dict:
        writes = {}
        if "monthly_usd" in values:
            writes[("budget", "monthly_usd")] = values["monthly_usd"]
        if "deep_dive_daily_usd" in values:
            writes[("deep_dive", "daily_usd")] = values["deep_dive_daily_usd"]
        if "x_monthly_usd" in values:
            writes[("x", "monthly_usd")] = values["x_monthly_usd"]
        if "search_monthly_usd" in values:
            writes[("search", "monthly_usd")] = values["search_monthly_usd"]
        setup.write_config_values(self._path(), writes)
        cfg = self.rt.cfg
        if "monthly_usd" in values:
            cfg = replace(cfg, budget=replace(cfg.budget, monthly_usd=values["monthly_usd"]))
            self.rt.llm.budget = cfg.budget
        if "deep_dive_daily_usd" in values:
            cfg = replace(cfg, deep_dive=replace(cfg.deep_dive,
                                                 daily_usd=values["deep_dive_daily_usd"]))
        if "x_monthly_usd" in values:
            cfg = replace(cfg, x=replace(cfg.x, monthly_usd=values["x_monthly_usd"]))
        if "search_monthly_usd" in values:
            cfg = replace(cfg, search=replace(cfg.search,
                                              monthly_usd=values["search_monthly_usd"]))
        self.rt.cfg = cfg
        return self._spend()

    async def set_spend(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        values = {}
        try:
            for key, what in (("monthly_usd", "watching's monthly cap"),
                              ("deep_dive_daily_usd", "the deep dives' daily slice"),
                              ("x_monthly_usd", "the X cap"),
                              ("search_monthly_usd", "the live search cap")):
                if key in body:
                    values[key] = usd_or_none(body[key], what)
        except setup.SetupError as exc:
            return _error(str(exc))
        if not values:
            return _error("nothing to set: send monthly_usd, deep_dive_daily_usd, "
                          "x_monthly_usd or search_monthly_usd")
        try:
            return JSONResponse(await run_in_threadpool(self._set_spend, values))
        except (OSError, setup.SetupError, config_mod.ConfigError) as exc:
            return _error(f"could not save: {exc}", 500)

    # -- reading (UP #3: the rows Settings › Watching said were set by hand) ----------------

    def _reading(self) -> dict:
        cfg = self.rt.cfg
        return {"every_hours": cfg.ingest.every_hours,
                "deep_dive": {"enabled": cfg.deep_dive.enabled,
                              "daily_usd": cfg.deep_dive.daily_usd},
                "every_hours_effect": "restart", "deep_dive_effect": "run",
                "config": self._path().name}

    async def reading(self, request: Request):
        try:
            return JSONResponse(await run_in_threadpool(self._reading))
        except setup.SetupError as exc:
            return _error(str(exc), 500)

    def _set_reading(self, values: dict) -> dict:
        writes = {}
        if "every_hours" in values:
            writes[("ingest", "every_hours")] = values["every_hours"]
        if "deep_dive_enabled" in values:
            writes[("deep_dive", "enabled")] = values["deep_dive_enabled"]
        setup.write_config_values(self._path(), writes)
        cfg = self.rt.cfg
        if "every_hours" in values:
            cfg = replace(cfg, ingest=replace(cfg.ingest, every_hours=values["every_hours"]))
        if "deep_dive_enabled" in values:
            cfg = replace(cfg, deep_dive=replace(cfg.deep_dive,
                                                 enabled=values["deep_dive_enabled"]))
        self.rt.cfg = cfg
        return self._reading()

    async def set_reading(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        values = {}
        if "every_hours" in body:
            h = body["every_hours"]
            lo, hi = EVERY_HOURS
            if isinstance(h, bool) or not isinstance(h, int | float) or not math.isfinite(h) \
                    or not lo <= h <= hi:
                return _error(f"every_hours is a number of hours from {lo:g} to {hi:g}")
            values["every_hours"] = int(h) if float(h).is_integer() else round(float(h), 2)
        if "deep_dive_enabled" in body:
            if not isinstance(body["deep_dive_enabled"], bool):
                return _error("deep_dive_enabled is true or false")
            values["deep_dive_enabled"] = body["deep_dive_enabled"]
        if not values:
            return _error("nothing to set: send every_hours or deep_dive_enabled")
        try:
            return JSONResponse(await run_in_threadpool(self._set_reading, values))
        except (OSError, setup.SetupError, config_mod.ConfigError) as exc:
            return _error(f"could not save: {exc}", 500)

    def routes(self) -> list[Route]:
        return [
            Route("/api/settings/models", self.models),
            Route("/api/settings/models", self.set_model, methods=["POST"]),
            Route("/api/settings/spend", self.spend),
            Route("/api/settings/spend", self.set_spend, methods=["POST"]),
            Route("/api/settings/reading", self.reading),
            Route("/api/settings/reading", self.set_reading, methods=["POST"]),
        ]
