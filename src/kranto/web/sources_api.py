"""Sources, the catalog and connected accounts over HTTP (section 5).

JSON endpoints for Kranto UI (the page's ``app.js`` at ``/brb/``), the
browser sign-in routes for connections, and their plain pages (``/connections``,
the sign-in's continue page): the only HTML the server still renders itself.

| Method and path                         | Does                                           |
|-----------------------------------------|------------------------------------------------|
| GET  /api/catalog                       | presets by provider, topics, connected accounts |
| GET  /api/sources                       | every source with status, health, topics        |
| GET  /api/sources/{id}                  | one source, its last seven fetches, how it is read |
| POST /api/sources/preview               | {preset, fields, topic}: one fetch, nothing saved |
| POST /api/sources                       | {preset, fields, topic} adds; {id, status} reviews |
| POST /api/sources/from-text             | {text, topic}: resolve a pasted list (202 + job) |
| GET  /api/sources/from-text[/{n}]       | the latest batch's job, or batch n's           |
| POST /api/sources/approve               | {ids, topic}: approve proposals in one request  |
| POST /api/sources/{id}/status           | {status}: approved, retired                     |
| POST /api/sources/{id}/fetch            | one fetch now, recorded, nothing judged         |
| POST /api/sources/{id}/retention        | {days}: a number, or null for the default       |
| POST /api/sources/{id}/mute             | {days}: 1-365, "less" (half its items), null: undo |
| POST /api/sources/{id}/keep             | keep one Kranto recommended removing       |
| POST /api/topics                        | {name, description, scout, kind, ref, approve}  |
| POST /api/topics/{id}/scout             | ask the scout for more sources (one model call) |
| GET  /api/connections                   | accounts, providers, how tokens are kept        |
| POST /api/connections/{id}/test         | one identity call                               |
| POST /api/connections/{id}/disconnect   | revoke where possible, then delete              |
| POST /api/connections/{p}/credentials   | paste a token, key or app password; YouTube's client |
| POST /connections/{provider}/start      | begin a sign-in (JSON: the URL; form: a link)   |
| GET  /connections/{provider}/callback   | finish it                                       |
| POST /connections/{provider}/device     | GitHub's device flow: a code to type at GitHub  |
| POST /connections/{provider}/device/poll| one poll, never faster than GitHub's interval   |

Sign-ins start only from a loopback host name (``localhost`` or ``127.0.0.1``):
the provider redirects the browser to that same name and port, which the SSH
tunnel carries to this server, so no port is opened. No token, prefix or part
of one is ever in a response.
"""

from __future__ import annotations

from urllib.parse import urlencode

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .. import library, source_health, sources
from ..connections import INFO, PROVIDER_INFO, OAuthError
from ..sources import catalog
from ..sources.reddit import FEEDS_END_NOTE

COOKIE = "afk_oauth"
# GitHub's device flow: no redirect comes back, so the browser holds the state.
DEVICE_COOKIE = "afk_device"
REDIRECT_HOSTS = ("localhost", "127.0.0.1")
REVIEW_STATUSES = ("approved", "retired", "proposed")
# ``POST /api/topics``'s ``approve``: what its scout approves at once (``App.scout_job``).
# none: everything waits for a person; core: core proposals at or above the prefilter line
# (the scout's ``--approve`` rule); all: every core proposal that test-fetched with items.
# Wildcards are never approved by the scout.
APPROVE_RULES = ("none", "core", "all")
STORAGE = {
    "where": "data/secrets/ in the workspace: connections.json and a salt file, readable by "
             "this user only (files 0600, directory 0700). Never in kranto.yaml, the library "
             "database, an export or a bundle.",
    "encrypted": "AES-256-GCM, with a key derived from this machine's id and the salt file. A "
                 "copy of the files is useless on another machine. This protects against copies "
                 "and backups, not against root on this box.",
    "refresh": "Tokens that expire are refreshed before a fetch; a token that cannot be "
               "refreshed, or that the site refuses, marks its sources Needs login, here and on "
               "their rows.",
    "disconnect": "Revokes the token at the site when the site has a revoke endpoint, then "
                  "deletes it here. You can also revoke it in the site's own settings.",
    "logs": "The HTTP client adds the token when a request is sent and never logs headers; "
            "error text is scrubbed before it is stored. Pages show an account name, scopes and "
            "dates, never a token or any part of one.",
}


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _hostname_and_port(request: Request) -> tuple[str, int]:
    host = request.headers.get("host", "")
    name, _, port = host.rpartition(":") if host.count(":") == 1 else (host, "", "")
    try:
        number = int(port) if port else (443 if request.url.scheme == "https" else 80)
    except ValueError:
        number = 80
    return (name or host).lower(), number


class SourcesAPI:
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

    # -- catalog and sources -------------------------------------------------------------

    def _topics(self) -> list[dict]:
        counts = {r["topic_id"]: r["n"] for r in self.rt.store.query(
            "SELECT topic_id, COUNT(*) AS n FROM topic_links ts WHERE (SELECT status FROM "
            "status_events s WHERE s.entity = 'source' AND s.entity_id = ts.source_id "
            "ORDER BY s.id DESC LIMIT 1) = 'approved' GROUP BY topic_id")}
        # every active topic, project topics too: this is the list a source is added to
        return [{"id": t.id, "name": t.name, "description": t.description, "kind": t.kind,
                 "ref": t.ref, "sources": counts.get(t.id, 0)}
                for t in library.active_topics(self.rt.store)]

    def _connected(self) -> dict:
        conns = self.rt.connections
        if conns is None:
            return {}
        out: dict = {}
        for a in conns.accounts():
            out.setdefault(a["provider"], []).append(
                {"instance": a["instance"], "account": a["account"], "state": a["state"]})
        return out

    def catalog(self, request: Request):
        return JSONResponse({**catalog.catalog_json(), "topics": self._topics(),
                             "connected": self._connected(),
                             "prefilter": self.rt.cfg.ingest.prefilter_min_similarity})

    def list_sources(self, request: Request):
        rows = source_health.list_sources(self.rt.store, self.rt.cfg)
        reddit = sum(1 for s in rows if s.get("kind") == "reddit"
                     and s.get("review") == "approved")
        conns = self.rt.connections
        return JSONResponse({
            "sources": rows, "topics": self._topics(),
            "reddit": {"watched": reddit, "note": FEEDS_END_NOTE},
            "connections_need_you": conns.needs_you() if conns is not None else 0,
            "every_hours": self.rt.cfg.ingest.every_hours,
            "default_retention_days": self.rt.cfg.retention.default_days})

    def one_source(self, request: Request):
        from .app import _int

        detail = source_health.source_detail(self.rt.store, self.rt.cfg,
                                             _int(request.path_params["source_id"], -1))
        if detail is None:
            return _error("no such source", 404)
        detail["every_hours"] = self.rt.cfg.ingest.every_hours
        return JSONResponse(detail)

    def _preset_args(self, body: dict):
        from .app import _int

        fields = body.get("fields") or {}
        if not isinstance(fields, dict):
            raise ValueError("fields must be an object")
        return str(body.get("preset") or ""), fields, _int(body.get("topic"))

    async def preview(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        try:
            preset, fields, topic = self._preset_args(body)
            result = await run_in_threadpool(source_health.preview, self.rt, preset, fields,
                                             topic)
        except (ValueError, TypeError) as exc:
            return _error(str(exc))
        except sources.SourceError as exc:
            state, text = source_health.fetch_state(exc)
            return JSONResponse({"error": text, "state": state}, status_code=422)
        return JSONResponse(result)

    async def add(self, request: Request):
        from .app import _int

        body, err = await self._body(request)
        if err:
            return err
        if body.get("id") is not None:
            return self._review(_int(body.get("id")), str(body.get("status") or "approved"),
                                _int(body.get("topic")))
        try:
            preset, fields, topic = self._preset_args(body)
            source_id, label = await run_in_threadpool(
                source_health.add_from_preset, self.rt, preset, fields, topic)
        except (ValueError, TypeError) as exc:
            return _error(str(exc))
        except sources.SourceError as exc:
            return _error(source_health.fetch_state(exc)[1], 422)
        return JSONResponse({"id": source_id, "label": label, "status": "approved"})

    def _review(self, source_id: int | None, status: str, topic_id: int | None = None):
        if status not in REVIEW_STATUSES:
            return _error(f"status must be one of {', '.join(REVIEW_STATUSES)}")
        if source_id not in {s.id for s in library.list_sources(self.rt.store)}:
            return _error("no such source", 404)
        self.rt.store.set_status("source", source_id, status, "via Kranto UI")
        if status == "approved" and topic_id and \
                topic_id in {t.id for t in library.active_topics(self.rt.store)}:
            library.link_topic_source(self.rt.store, topic_id, source_id)
        return JSONResponse({"id": source_id, "status": status})

    async def set_status(self, request: Request):
        from .app import _int

        body, err = await self._body(request)
        if err:
            return err
        return self._review(_int(request.path_params["source_id"]),
                            str(body.get("status") or ""))

    async def fetch(self, request: Request):
        from .app import _int

        try:
            result = await run_in_threadpool(source_health.fetch_now, self.rt,
                                             _int(request.path_params["source_id"], -1))
        except ValueError as exc:
            return _error(str(exc), 404 if "no source" in str(exc) else 400)
        return JSONResponse(result)

    async def retention(self, request: Request):
        from ..retention import retention_days, set_source_retention
        from .app import _int

        body, err = await self._body(request)
        if err:
            return err
        source_id = _int(request.path_params["source_id"], -1)
        days = body.get("days")
        if days is not None and (isinstance(days, bool) or not isinstance(days, int | float)):
            return _error("days must be a number of days (0: keep forever) or null")
        try:
            set_source_retention(self.rt.store, source_id, days, "via Kranto UI")
        except ValueError as exc:
            return _error(str(exc), 404 if "no source" in str(exc) else 400)
        return JSONResponse({"id": source_id, "days": days,
                             "effective_days": retention_days(self.rt.store,
                                                              self.rt.cfg.retention)[source_id]})

    async def mute(self, request: Request):
        """Mute a source for some days, have it read less, or undo either."""
        from .app import _int

        body, err = await self._body(request)
        if err:
            return err
        source_id = _int(request.path_params["source_id"], -1)
        days = body.get("days")
        less = days == "less"
        if not less and days is not None and (isinstance(days, bool)
                                              or not isinstance(days, int | float)):
            return _error('days must be a number of days, "less", or null to undo')
        try:
            mute = source_health.set_mute(self.rt.store, source_id,
                                          days=None if less else days, read_less=less,
                                          note="via Kranto UI")
        except ValueError as exc:
            return _error(str(exc), 404 if "no source" in str(exc) else 400)
        label = next((s.label for s in library.list_sources(self.rt.store)
                      if s.id == source_id), "")
        return JSONResponse({"id": source_id, "label": label, **mute})

    async def keep(self, request: Request):
        """Keep a source the source rule recommended removing (``source_rule.keep``): its row
        goes from Needs you, and only downvotes given from now count toward the next one."""
        from .. import source_rule
        from .app import _int

        source_id = _int(request.path_params["source_id"], -1)
        try:
            got = source_rule.keep(self.rt.store, source_id,
                                   getattr(self.rt.cfg, "grading", None))
        except ValueError as exc:
            return _error(str(exc), 404 if "no source" in str(exc) else 400)
        label = next((s.label for s in library.list_sources(self.rt.store)
                      if s.id == source_id), "")
        return JSONResponse({**got, "label": label})

    async def add_topic(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        kind = body.get("kind") or "user"
        ref = body.get("ref")
        approve = body.get("approve") or "none"
        if approve not in APPROVE_RULES:
            return _error(f"approve must be one of {', '.join(APPROVE_RULES)}")
        try:
            topic_id, existing = await run_in_threadpool(
                lambda: library.add_topic_once(
                    self.rt.store, self.rt.embedder, str(body.get("name") or ""),
                    str(body.get("description") or ""), kind=str(kind),
                    ref=ref if ref is None else str(ref)))
        except ValueError as exc:
            return _error(str(exc))
        topic = next(t for t, _, _ in library.topics_with_status(self.rt.store)
                     if t.id == topic_id)
        out = {"id": topic_id, "kind": topic.kind, "ref": topic.ref, "existing": existing,
               "message": None, "proposals": [], "invalid": 0}
        if existing:
            # a project topic is keyed by its ref: the same POST again starts nothing
            return JSONResponse(out)
        if body.get("scout"):
            # the scout calls the model: it runs in the background, the page polls its job
            out["job"] = self.app.scout_job(topic_id, approve)
        return JSONResponse(out)

    async def scout(self, request: Request):
        """``POST``: start the topic's scout in the background and answer at once (202,
        ``{"job"}``; a scout already running is that one); ``GET``: its job, with ``result``
        ``{message, proposals, invalid}`` once done."""
        from .app import _int

        topic_id = _int(request.path_params["topic_id"], -1)
        if topic_id not in {t.id for t in library.active_topics(self.rt.store)}:
            return _error("no such topic", 404)
        if request.method == "GET":
            job = self.app.jobs.get(f"scout:{topic_id}")
            if job is None:
                return _error("this topic has no scout running or finished", 404)
            return JSONResponse({"job": job})
        return JSONResponse({"job": self.app.scout_job(topic_id)}, status_code=202)

    # -- sources described in a pasted text --------------------------------

    async def from_text(self, request: Request):
        """``POST {text, topic?}``: resolve a pasted list in the background and answer at once
        (202, ``{"job"}``; one already running is that one); ``GET``: the latest batch's job,
        with ``result`` (the batch) once done."""
        from .app import _int

        if request.method == "GET":
            job = self.app.jobs.get("fromtext")
            if job is None:
                return _error("no described list has been resolved since Kranto started", 404)
            return JSONResponse({"job": job})
        body, err = await self._body(request)
        if err:
            return err
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            return _error("text must be the pasted list or description (not empty)")
        topic_id = _int(body.get("topic"))
        if topic_id is not None and \
                topic_id not in {t.id for t in library.active_topics(self.rt.store)}:
            return _error("no such topic", 404)
        return JSONResponse({"job": self.app.fromtext_job(text, topic_id)}, status_code=202)

    def from_text_batch(self, request: Request):
        """``GET``: one batch again by its id (the number in ``fromtext:<n>``)."""
        job = self.app.jobs.get(f"fromtext:{request.path_params['batch']}")
        if job is None:
            return _error("no such batch (batches are kept for the last 200 jobs)", 404)
        return JSONResponse({"job": job})

    async def approve(self, request: Request):
        """``POST {ids: [...], topic?}``: approve proposals in one request (D3); each one
        already watched is only linked to the topic. ``{approved, skipped}``."""
        from ..resolve import approve
        from .app import _int

        body, err = await self._body(request)
        if err:
            return err
        ids = body.get("ids")
        if not isinstance(ids, list) or not ids or \
                not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            return _error("ids must be a list of source ids")
        topic = _int(body.get("topic"))
        try:
            result = approve(self.rt.store, ids, topic, note="via Kranto UI")
        except ValueError as exc:
            return _error(str(exc), 404)
        result["first_read"] = self._first_read(topic, result)
        return JSONResponse(result)

    def _first_read(self, topic: int | None, result: dict) -> str | None:
        """Watch these on a topic never read starts its first read now (the topic's
        page then shows it reading, and its first brief follows): ``started``, ``busy`` (a job
        is running; the read starts after it, at its time) or None when nothing was started (no
        topic, nothing approved, a topic read before, no scheduler, or setup not done: Welcome's
        own finish starts it)."""
        from .. import setup
        from ..progress import first_read_at

        scheduler = getattr(self.app, "scheduler", None)
        if topic is None or scheduler is None or not result.get("approved") or \
                not setup.is_done(self.rt.store) or first_read_at(self.rt.store, topic):
            return None
        return "started" if scheduler.trigger("ingest", origin="press", by="ui") else "busy"

    # -- connections ---------------------------------------------------------------------

    def _providers(self) -> list[dict]:
        conns = self.rt.connections
        return conns.provider_info() if conns is not None else PROVIDER_INFO

    def connections(self, request: Request):
        conns = self.rt.connections
        accounts = conns.accounts() if conns is not None else []
        browser = [k for k, p in (conns.providers.items() if conns is not None else [])
                   if p.browser]
        return JSONResponse({
            "accounts": accounts,
            "providers": self._providers(),
            "unavailable": conns.unavailable() if conns is not None else "not configured",
            "storage": STORAGE,
            "callback": {p: f"/connections/{p}/callback" for p in browser},
        })

    async def credentials(self, request: Request):
        """Paste a token, a key or an app password (tested before it is kept), or
        YouTube's client id and secret (``{"clear": true}`` removes them)."""
        provider = request.path_params["provider"]
        body, err = await self._body(request)
        if err:
            return err
        conns = self.rt.connections
        if conns is None or provider not in INFO:
            return _error("no such provider", 404)
        fields = {k: v for k, v in body.items() if isinstance(v, str)}
        try:
            if INFO[provider].get("flow") == "client":
                if body.get("clear"):
                    await run_in_threadpool(conns.clear_client, provider)
                    return JSONResponse({"ok": True,
                                         "message": INFO[provider]["client_removed"]})
                await run_in_threadpool(conns.set_client, provider, fields)
                return JSONResponse({"ok": True, "message": "Saved. Now click Connect."})
            conn = await run_in_threadpool(conns.paste, provider, fields)
        except OAuthError as exc:
            return _error(str(exc))
        said = f" {conn['said']}" if conn.get("said") else ""
        return JSONResponse({"ok": True, "account": conn["account"],
                             "message": f"Connected {INFO[provider]['name']} {conn['account']}."
                             + said})

    async def device_start(self, request: Request):
        provider = request.path_params["provider"]
        conns = self.rt.connections
        if conns is None or provider not in INFO:
            return _error("no such provider", 404)
        try:
            cookie, shown = await run_in_threadpool(conns.device_start, provider)
        except OAuthError as exc:
            return _error(str(exc))
        response = JSONResponse(shown)
        response.set_cookie(DEVICE_COOKIE, cookie, max_age=900, path="/connections/",
                            httponly=True, samesite="strict")
        return response

    async def device_poll(self, request: Request):
        provider = request.path_params["provider"]
        conns = self.rt.connections
        if conns is None or provider not in INFO:
            return _error("no such provider", 404)
        try:
            result = await run_in_threadpool(conns.device_poll, provider,
                                             request.cookies.get(DEVICE_COOKIE))
        except OAuthError as exc:
            response = _error(str(exc))
            response.delete_cookie(DEVICE_COOKIE, path="/connections/")
            return response
        response = JSONResponse(result)
        if result["state"] != "pending":
            response.delete_cookie(DEVICE_COOKIE, path="/connections/")
        return response

    async def test(self, request: Request):
        from .app import _int

        conns = self.rt.connections
        if conns is None:
            return _error("connections are not available here")
        try:
            result = await run_in_threadpool(conns.test, _int(request.path_params["conn_id"], -1))
        except OAuthError as exc:
            return _error(str(exc), 404)
        return JSONResponse(result)

    async def disconnect(self, request: Request):
        from .app import _int

        conns = self.rt.connections
        if conns is None:
            return _error("connections are not available here")
        try:
            note = await run_in_threadpool(conns.disconnect,
                                           _int(request.path_params["conn_id"], -1))
        except OAuthError as exc:
            return _error(str(exc), 404)
        return JSONResponse({"ok": True, "message": f"Disconnected: {note}."})

    async def start(self, request: Request):
        provider = request.path_params["provider"]
        wants_json = request.headers.get("content-type", "").startswith("application/json")
        if wants_json:
            body, err = await self._body(request)
            if err:
                return err
        else:
            body = dict(await request.form())
        hostname, port = _hostname_and_port(request)
        conns = self.rt.connections

        def refuse(message: str):
            if wants_json:
                return _error(message)
            return self.app.render("connections.html", request, nav="connections",
                                   **self._page_ctx(), message=message)

        if hostname not in REDIRECT_HOSTS:
            return refuse("Open this page as http://localhost:" + str(port) + " (or "
                          "127.0.0.1) to connect an account: the site sends your browser back "
                          "to that address, through your SSH tunnel.")
        if conns is None or provider not in INFO or provider not in conns.providers:
            return refuse("No such provider.")
        needed = conns.providers[provider].redirect_host
        if needed and hostname != needed:
            # The sign-in cookie belongs to the host name the page is open on, and the
            # provider sends the browser back to this one: they must be the same.
            return refuse(f"Open this page as http://{needed}:{port} to connect "
                          f"{INFO[provider]['name']}: it only sends your browser back to "
                          f"{needed}, not to {hostname}.")
        redirect_uri = f"http://{hostname}:{port}/connections/{provider}/callback"
        value = str(body.get("instance") or body.get("handle") or "")
        try:
            url, state_id = await run_in_threadpool(conns.start, provider, value, redirect_uri)
        except OAuthError as exc:
            return refuse(str(exc))
        if wants_json:
            response = JSONResponse({"authorize_url": url, "callback": redirect_uri})
        else:
            # A form cannot redirect to another site under the page's form-action
            # policy; the page offers the link instead.
            response = self.app.render("connect_continue.html", request, nav="connections",
                                       url=url, provider=INFO[provider]["name"],
                                       callback=redirect_uri)
        response.set_cookie(COOKIE, str(state_id), max_age=600, path="/connections/",
                            httponly=True, samesite="lax")
        return response

    async def callback(self, request: Request):
        provider = request.path_params["provider"]
        conns = self.rt.connections
        query = {k: request.query_params.get(k) for k in ("state", "code", "error", "iss")}
        try:
            if conns is None:
                raise OAuthError("connections are not available here")
            conn = await run_in_threadpool(conns.finish, provider,
                                           request.cookies.get(COOKIE), query)
            outcome = {"connected": f"{INFO[provider]['name']} {conn['account']}"}
        except OAuthError as exc:
            outcome = {"error": str(exc)}
        except KeyError:
            outcome = {"error": "no such provider"}
        if self.app.brb.mounted:
            target = "/#/settings/connections?" + urlencode(outcome)
        else:
            target = "/connections?" + urlencode(
                {"msg": f"Connected {outcome['connected']}." if "connected" in outcome
                 else f"Not connected: {outcome['error']}"})
        response = RedirectResponse(target, status_code=303)
        response.delete_cookie(COOKIE, path="/connections/")
        return response

    # -- the server's own pages ---------------------------------------------------------------

    def _page_ctx(self) -> dict:
        conns = self.rt.connections
        return {"accounts": conns.accounts() if conns is not None else [],
                "providers": self._providers(), "storage": STORAGE,
                "unavailable": conns.unavailable() if conns is not None else "not configured"}

    async def credentials_form(self, request: Request):
        """The plain-form twin of ``credentials``, for the server's own /connections page."""
        provider = request.path_params["provider"]
        conns = self.rt.connections
        if conns is None or provider not in INFO:
            return Response("bad request", status_code=400)
        fields = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
        try:
            if INFO[provider].get("flow") == "client":
                await run_in_threadpool(conns.set_client, provider, fields)
                msg = f"Saved {INFO[provider]['name']}'s client. Now click Connect."
            else:
                conn = await run_in_threadpool(conns.paste, provider, fields)
                msg = f"Connected {INFO[provider]['name']} {conn['account']}." + (
                    f" {conn['said']}" if conn.get("said") else "")
        except OAuthError as exc:
            msg = f"Not connected: {exc}"
        return RedirectResponse(self.app.links.connections(msg), status_code=303)

    def connections_page(self, request: Request):
        return self.app.render("connections.html", request, nav="connections",
                               **self._page_ctx(), message=request.query_params.get("msg"))

    async def connection_form(self, request: Request):
        from .app import _int

        action = request.path_params["action"]
        conn_id = _int(request.path_params["conn_id"], -1)
        conns = self.rt.connections
        if conns is None or action not in ("test", "disconnect"):
            return Response("bad request", status_code=400)
        try:
            if action == "test":
                result = await run_in_threadpool(conns.test, conn_id)
                msg = result["message"]
            else:
                msg = "Disconnected: " + await run_in_threadpool(conns.disconnect, conn_id) + "."
        except OAuthError as exc:
            msg = str(exc)
        return RedirectResponse(self.app.links.connections(msg), status_code=303)

    def routes(self) -> list[Route]:
        return [
            Route("/api/catalog", self.catalog),
            Route("/api/sources", self.list_sources),
            Route("/api/sources", self.add, methods=["POST"]),
            Route("/api/sources/preview", self.preview, methods=["POST"]),
            Route("/api/sources/from-text", self.from_text, methods=["GET", "POST"]),
            Route("/api/sources/from-text/{batch:int}", self.from_text_batch),
            Route("/api/sources/approve", self.approve, methods=["POST"]),
            Route("/api/sources/{source_id}", self.one_source),
            Route("/api/sources/{source_id}/status", self.set_status, methods=["POST"]),
            Route("/api/sources/{source_id}/fetch", self.fetch, methods=["POST"]),
            Route("/api/sources/{source_id}/retention", self.retention, methods=["POST"]),
            Route("/api/sources/{source_id}/mute", self.mute, methods=["POST"]),
            Route("/api/sources/{source_id}/keep", self.keep, methods=["POST"]),
            Route("/api/topics", self.add_topic, methods=["POST"]),
            Route("/api/topics/{topic_id}/scout", self.scout, methods=["GET", "POST"]),
            Route("/api/connections", self.connections),
            Route("/api/connections/{conn_id}/test", self.test, methods=["POST"]),
            Route("/api/connections/{conn_id}/disconnect", self.disconnect, methods=["POST"]),
            Route("/api/connections/{provider}/credentials", self.credentials,
                  methods=["POST"]),
            Route("/connections", self.connections_page),
            Route("/connections/{conn_id:int}/{action}", self.connection_form,
                  methods=["POST"]),
            Route("/connections/{provider}/credentials", self.credentials_form,
                  methods=["POST"]),
            Route("/connections/{provider}/device", self.device_start, methods=["POST"]),
            Route("/connections/{provider}/device/poll", self.device_poll, methods=["POST"]),
            Route("/connections/{provider}/start", self.start, methods=["POST"]),
            Route("/connections/{provider}/callback", self.callback),
        ]
