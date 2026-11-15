"""The page as Kranto sees it, without the page: a stand-in ``kranto.page.host_api``. Kranto imports
the page through that one module (the page's S-12), so a test puts only the names it
needs there; a name it leaves out is missing, and ``from kranto.page.host_api import it`` raises
ImportError, as it does with a version of the page that has no such part."""
from __future__ import annotations

import sys
import types


def install(monkeypatch, api: types.ModuleType | None = None, **names) -> types.ModuleType:
    """Put ``api`` (else this test's stand-in so far, else a new one) in place of
    ``kranto.page.host_api``, with ``names`` set on it."""
    cur = sys.modules.get("kranto.page.host_api")
    if api is None:
        api = cur if getattr(cur, "_stand_in", False) else types.ModuleType("kranto.page.host_api")
    api._stand_in = True
    if not hasattr(api, "HOST_API_VERSION"):
        api.HOST_API_VERSION = 1
    for k, v in names.items():
        setattr(api, k, v)
    pkg = types.ModuleType("kranto.page")
    pkg.__path__ = []
    pkg.host_api = api
    monkeypatch.setitem(sys.modules, "kranto.page", pkg)
    monkeypatch.setitem(sys.modules, "kranto.page.host_api", api)
    return api


def drop(monkeypatch, *names: str) -> None:
    """An older page: this test's stand-in no longer has ``names``."""
    api = install(monkeypatch)
    for n in names:
        if hasattr(api, n):
            monkeypatch.delattr(api, n)


def missing(monkeypatch) -> None:
    """No the page at all: every import of it fails."""
    for name in ("kranto.page", "kranto.page.host_api"):
        monkeypatch.setitem(sys.modules, name, None)
