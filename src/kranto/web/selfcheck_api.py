"""What the post-update self-check reads.

``GET /api/selfcheck/paths``: every GET this server answers that the page reads, as concrete
paths on this install's own data, for ``update/apply.py``'s ``route_check`` (after ``kranto
update`` restarts on a new version, and ``kranto doctor --routes``):

- every API route that takes no id: each list's first page, the home, the activity, the
  settings' reads;
- every topic's page (archived ones too) and every source's, each cub's page and each of every
  feature's reads (a cub's page data, News's briefs, the radar's trends), the core's v1 reads;
- the page's server's reads (the page's ``host_api.selfcheck_paths``, under ``/brb``).

Left out, each with its reason (``excluded``): what reaches past this machine or runs a program
(a live web search, a page fetch, the logins' check), and this list. A read that needs a query
answers 400, which the check counts as an answer: only 500 and above, or none, fail it. Nothing
here writes or calls a model.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

PATHS = "/api/selfcheck/paths"
EXCLUDED = {
    "/api/websearch": "a live web search (the network)",
    "/api/websearch/fetch": "fetches a page from the web",
    "/api/setup": "runs claude and gh to read their logins",
    "/api/setup/provider": "runs claude to read its login",
    PATHS: "this list",
}
# the page's server's reads when its the page gives no list of its own (before 0.5.23, or one
# whose list failed): only reads that stay after the cut (the builds', loop's and projects'
# reads left with them)
BRB_FALLBACK = ("/api/header", "/api/activity")


class SelfCheckAPI:
    def __init__(self, app, routes) -> None:
        self.app = app
        self.app_routes = routes        # a function: the app's routes, once they are made

    @property
    def rt(self):
        return self.app.rt

    def paths(self) -> list[str]:
        from .. import library
        from ..core import registry
        from ..core.api import reads

        first = ["/api/status", "/api/home", "/api/topics", "/api/sources", "/api/today",
                 "/api/activity"]
        out = list(first)
        for r in self.app_routes():
            if not isinstance(r, Route) or "GET" not in (r.methods or ()):
                continue
            if r.path.startswith("/api/") and "{" not in r.path and r.path not in EXCLUDED:
                out.append(r.path)
        out.append("/api/topics?kind=all")
        store = self.rt.store
        out += [f"/api/topics/{t.id}" for t, _, _ in
                library.topics_with_status(store, archived=True)]
        out += [f"/api/sources/{s.id}" for s in library.list_sources(store)]
        out += [f"/api/read/{name}" for name in reads()]
        try:
            from ..core.cubs import registry as cub_registry
            out += [f"/api/cubs/{cid}" for cid, row in
                    sorted(cub_registry.latest_rows(store).items())
                    if row["state"] != "removed"]
        except Exception:  # noqa: BLE001 - a broken cubs table is the cubs list's to say
            out.append("/api/cubs")
        for f in registry.features():
            if registry.enabled(self.rt.cfg, f):
                out += [f"/api/f/{f.id}/{name}" for name in sorted(f.api)]
        brb = getattr(self.app, "brb", None)
        if brb is not None and brb.mounted:
            fn = getattr(brb.api, "selfcheck_paths", None)
            try:
                theirs = list(fn()) if fn is not None else list(BRB_FALLBACK)
            except Exception:  # noqa: BLE001 - the builds UI's own reads still say it
                theirs = list(BRB_FALLBACK)
            out += ["/brb/"] + ["/brb" + p for p in theirs if isinstance(p, str)
                                and p.startswith("/")]
        return list(dict.fromkeys(out))

    def index(self, request: Request):
        return JSONResponse({"paths": self.paths(), "excluded": EXCLUDED})

    def routes(self) -> list[Route]:
        return [Route(PATHS, self.index)]
