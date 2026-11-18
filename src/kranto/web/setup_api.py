"""First-run setup over HTTP, for Kranto UI's ``#/welcome`` and Settings › Watching.

| Method and path          | Does                                                          |
|--------------------------|---------------------------------------------------------------|
| GET  /api/setup          | done or not; key set and its last test; the two logins; counts |
| GET  /api/setup/provider | what can serve the watcher's models (providers.detect)         |
| POST /api/setup/provider | {provider, key?, base_url?, terms?, replace}: test, then make  |
|                          | it the watcher's (claude_code needs terms: true, its sentence  |
|                          | shown where it was chosen);                                   |
|                          | watcher's (providers.choose); the server uses it at once       |
| POST /api/watch/resume   | end a provider's pause now (a spend limit raised): watching    |
|                          | goes on at its next run                                        |
| POST /api/setup/check    | test the two logins again now                                  |
| POST /api/setup/finish   | {build_mode, concurrency}: write the config (and, with builds  |
|                          | on, the loop's intake.auto.mode and concurrency), mark setup   |
|                          | done, start the first read (Welcome's Start reading)           |

``GET /api/setup``'s ``cost`` is Welcome's Ready line: what Kranto costs on the
person's own key, and the monthly cap or "No cap is set".

These are the only writers of ``.env`` and of the values onboarding sets in the YAML.
Once setup is done, ``provider`` and ``finish`` refuse unless the body says ``replace: true``
(Settings › Watching does). No response, log line or stored row holds the key.
"""

from __future__ import annotations

from dataclasses import replace

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import config as config_mod
from .. import library, providers, setup


def _error(message: str, status: int = 400, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


class SetupAPI:
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

    def _config_path(self):
        # the file the server loaded: kranto.yaml in a kranto home, else kranto.yaml
        return config_mod.config_path(self.rt.cfg.root)

    def _state(self, fresh: bool = False) -> dict:
        store, cfg = self.rt.store, self.rt.cfg
        topics = [t for t in library.active_topics(store) if t.kind == "user"]
        approved = library.list_sources(store, "approved")
        key_set = self.rt.llm.has_key
        done_at = store.get_setting(setup.DONE)
        logins = setup.logins(fresh=fresh)
        use = providers.in_use(cfg.llm)
        return {
            "done": bool(done_at), "done_at": done_at,
            # a fresh install lands on #/welcome; an installation that already reads
            # topics with a key (adopted) does not
            "needs_setup": not done_at and (not key_set or not topics),
            "key": {"set": key_set, "env": cfg.llm.key_env or "", "base_url": cfg.llm.base_url,
                    "provider": cfg.llm.provider_name, "choice": use["choice"],
                    "label": use["label"], "endpoint": use["endpoint"],
                    "test": setup.last_key_test(store)},
            "logins": logins,
            "builds_ok": all(v["ok"] for v in logins.values()),
            "build": setup.build_choice(store),
            "topics": len(topics), "sources": len(approved),
            "scheduler": self.app.scheduler is not None,
            "budget_usd": cfg.budget.monthly_usd,
            "cost": setup.cost_words(cfg.budget.monthly_usd, use["provider"]),
            # the first brief's estimate on Ready: minutes, from the
            # walks' pace and five places
            "first_brief_minutes": 5,
            "every_hours": cfg.ingest.every_hours,
            "brb": self.app.brb.mounted,
            # builds.enabled: off, Welcome is the key, the topic, done
            "builds": config_mod.builds_on(cfg),
        }

    async def state(self, request: Request):
        fresh = request.query_params.get("fresh") == "1"
        return JSONResponse(await run_in_threadpool(self._state, fresh))

    async def check(self, request: Request):
        return JSONResponse(await run_in_threadpool(self._state, True))

    async def provider_state(self, request: Request):
        return JSONResponse(await run_in_threadpool(providers.detect, self.rt.cfg.root))

    async def provider(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        store = self.rt.store
        if setup.is_done(store) and body.get("replace") is not True:
            return _error("setup is done: change the watching model under Settings › Watching", 409)
        name = str(body.get("provider") or "")
        raw_key = body.get("key")
        key = str(raw_key) if raw_key not in (None, "") else None
        base_url = body.get("base_url") or None
        terms = body.get("terms") is True
        try:
            result = await run_in_threadpool(self._choose, name, key, base_url, terms)
        except (setup.SetupError, config_mod.ConfigError) as exc:
            return _error(setup.scrub_key(str(exc), key or ""))
        except OSError as exc:
            return _error(setup.scrub_key(f"the key works but could not be saved: {exc}",
                                          key or ""), 500)
        test = setup.record_key_test(store, providers.KeyTest(result["test"]["ok"],
                                                              result["test"]["detail"]),
                                     result.get("base_url") or name)
        if not result["ok"]:
            return _error(result["test"]["detail"], test=test)
        return JSONResponse({**result, "test": test})

    def _choose(self, name: str, key: str | None, base_url: str | None,
                terms: bool = False) -> dict:
        """providers.choose, then the running server takes the new provider and key. A
        preview tests no key (``preview.NO_KEY_TEST``: the test is a request to the provider);
        Claude Code's check is this machine's own and still runs."""
        from .. import preview
        cfg = self.rt.cfg
        if name != "claude_code" and preview.enabled(cfg.root):
            raise setup.SetupError(preview.NO_KEY_TEST)
        result = providers.choose(cfg.root, name, key=key, base_url=base_url, terms=terms)
        if result["ok"]:
            llm_cfg = config_mod.load(cfg.root, dotenv=False).llm
            self.rt.cfg = replace(cfg, llm=llm_cfg)
            if key is not None and result["env"]:
                self.rt.llm.use_provider_key(result["env"], key)
            self.rt.llm.config = llm_cfg
        return result

    async def watch_resume(self, request: Request):
        from ..llm import WATCH_PAUSE_KEY
        was = self.rt.store.get_setting(WATCH_PAUSE_KEY) is not None
        self.rt.store.delete_setting(WATCH_PAUSE_KEY)
        return JSONResponse({"ok": True, "was_paused": was})

    async def finish(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        store = self.rt.store
        if setup.is_done(store) and body.get("replace") is not True:
            return _error("setup is already done", 409)
        if not self.rt.llm.has_key:
            return _error("set the model key first (step 1)")
        concurrency = body.get("concurrency", 1)
        mode = str(body.get("build_mode") or "auto")
        try:
            at = setup.mark_done(store, mode, concurrency)
        except setup.SetupError as exc:
            return _error(str(exc))
        base = str(request.base_url).rstrip("/")
        path = self._config_path()
        # kranto serve takes its port from notify.base_url: a browser on another port (an
        # SSH tunnel, a proxy) must not move the server on its next start
        port = getattr(self.app, "port", None)
        if port and (request.url.port or 80) != port:
            path = None
        if path is not None and base != self.rt.cfg.notify.base_url:
            try:
                await run_in_threadpool(setup.write_config_values, path,
                                        {("notify", "base_url"): base})
                self.rt.cfg = replace(self.rt.cfg,
                                      notify=replace(self.rt.cfg.notify, base_url=base))
            except (OSError, setup.SetupError) as exc:
                return _error(f"setup is marked done, but {path.name} was not updated: {exc}",
                              500)
        return JSONResponse({"done": True, "at": at, "ingest": self._first_ingest(),
                             "build": setup.build_choice(store),
                             # builds left Kranto: no loop.yaml is written; kept for a
                             # page that reads the key
                             "loop_settings": None})

    def _first_ingest(self) -> str:
        if self.app.scheduler is None:
            return "no_scheduler"
        if not library.list_sources(self.rt.store, "approved"):
            return "no_sources"
        return "started" if self.app.scheduler.trigger("ingest") else "busy"

    def routes(self) -> list[Route]:
        return [
            Route("/api/setup", self.state),
            Route("/api/setup/provider", self.provider_state),
            Route("/api/setup/provider", self.provider, methods=["POST"]),
            Route("/api/watch/resume", self.watch_resume, methods=["POST"]),
            Route("/api/setup/check", self.check, methods=["POST"]),
            Route("/api/setup/finish", self.finish, methods=["POST"]),
        ]
