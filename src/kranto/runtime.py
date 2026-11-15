"""Wiring: build the long-lived objects a command or the server needs."""

from __future__ import annotations

from dataclasses import dataclass

from . import config as config_mod
from . import prompts
from .connections import Connections
from .embed import Embedder, NomicEmbedder
from .llm import LLMClient
from .search import Index
from .sources import HTTP, pacing
from .store import Store


@dataclass
class Runtime:
    cfg: config_mod.Config
    store: Store
    llm: LLMClient
    embedder: Embedder
    http: HTTP
    index: Index
    connections: Connections | None = None
    # the cub runtime (core.cubs.runtime.CubRuntime), made by the server
    cubs: object | None = None

    def close(self) -> None:
        self.llm.close()
        self.http.close()
        self.store.close()


def open_runtime(
    cfg: config_mod.Config,
    *,
    store: Store | None = None,
    embedder: Embedder | None = None,
    llm: LLMClient | None = None,
    http: HTTP | None = None,
    connections: Connections | None = None,
) -> Runtime:
    store = store or Store.open(cfg.db_path)
    # Pacing is per host and process-wide: every HTTP the runtime makes shares it.
    pacing.HOSTS.configure(cfg.fetch)
    # The owner's prompt additions and overrides live in this workspace (the kranto home).
    prompts.configure(cfg.root)
    embedder = embedder or NomicEmbedder()
    http = http or HTTP()
    rt = Runtime(
        cfg=cfg,
        store=store,
        llm=llm or LLMClient(store, cfg.llm, cfg.budget),
        embedder=embedder,
        http=http,
        index=Index(store, embedder.model_name),
        connections=connections or Connections(
            store, cfg.data_dir, http, enabled=cfg.connections.enabled,
            github_client_id=cfg.connections.github_client_id),
    )
    # builds off (absent means off,.1): project topics are held as paused and
    # the build loop's actions are not verbs, in every process that opens a runtime
    from . import library
    from .core import verbs
    on = config_mod.builds_on(cfg)
    library.configure(held_kinds=() if on else ("project",))
    # and the verbs of what else is off read this runtime's config (PR 1.2): a feature that is
    # off, the browser without browser.enabled, the cub shop without cubs.developer
    verbs.configure(builds=on, rt=rt)
    # a feature that is off loads no skill of its own in the console (PR 1.2)
    from . import assistant
    try:
        from .core import registry
        off = {f.id for f in registry.first_party() if not registry.enabled(cfg, f)}
    except Exception:  # noqa: BLE001 - a registry that cannot load leaves every skill
        off = set()
    assistant.configure(off_features=off)
    # sources watched through live search read with this install's searcher
    from . import websearch
    websearch.configure(websearch.for_runtime(rt, caller="sources"))
    return rt
